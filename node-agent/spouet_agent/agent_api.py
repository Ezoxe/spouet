"""Mini FastAPI — plan de contrôle du node-agent (port 8765).

Endpoints appelés par le backend Spouet pour piloter llama.cpp :
  GET  /status              → état + stats llama-server
  GET  /models              → liste GGUF locaux
  POST /models/download     → lance téléchargement HuggingFace async
  GET  /models/download/status → progrès du dernier téléchargement
  POST /models/load         → change le modèle actif (redémarre llama-server)
  GET  /load/status         → état explicite du chargement (idle/loading/ready/error)
  DELETE /models/{filename} → supprime un GGUF
  PATCH /config             → change les params llama.cpp (redémarre llama-server)
  GET  /diag/llama          → dernières lignes du process llama-server (debug)
"""

from __future__ import annotations

import asyncio
import time
import traceback
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

app = FastAPI(title="spouet-agent control API", docs_url=None, redoc_url=None)

# Références injectées depuis main.py au démarrage
_server: Any = None  # LlamaServer instance
_models_dir: Path | None = None
_gpu_info: Any = None  # GpuInfo (legacy : VRAM/RAM/disk pour le heartbeat)
_capabilities: Any = None  # NodeCapabilities (source de vérité hardware)
_download_status: dict = {"status": "idle"}

# État explicite du chargement llama-server (utilisé par le backend pour
# attendre la fin d'un cold-start avant de POSTer sur /v1/chat/completions).
_load_status: dict[str, Any] = {
    "state": "idle",          # idle | loading | ready | error
    "filename": None,
    "error": None,
    "started_at": None,
    "ready_at": None,
}
_load_lock = asyncio.Lock()


def init(
    server: Any,
    models_dir: Path,
    gpu_info: Any,
    capabilities: Any = None,
    autoload_filename: str | None = None,
    autoload_error: str | None = None,
) -> None:
    global _server, _models_dir, _gpu_info, _capabilities
    _server = server
    _models_dir = models_dir
    _gpu_info = gpu_info
    _capabilities = capabilities
    # Si un modèle a été autoloadé avec succès au boot, refléter l'état dans
    # _load_status pour que le backend voie `ready` au lieu de `idle`. Si
    # l'autoload a échoué, exposer l'erreur explicitement.
    current = getattr(server, "_current_model", None)
    is_running = server.is_running() if hasattr(server, "is_running") else False
    if current is not None and is_running:
        _load_status.update(
            state="ready",
            filename=current.name,
            error=None,
            ready_at=time.time(),
        )
    elif autoload_error:
        _load_status.update(
            state="error",
            filename=autoload_filename,
            error=autoload_error,
            ready_at=time.time(),
        )


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@app.get("/status")
async def get_status() -> dict:
    from spouet_agent.model_manager import list_local_models
    stats = await _server.get_stats() if _server else None
    models = list_local_models(_models_dir) if _models_dir else []
    return {
        "llama_running": stats.running if stats else False,
        "llama_model_loaded": stats.model_loaded if stats else None,
        "llama_n_ctx": stats.n_ctx if stats else None,
        "llama_n_gpu_layers": stats.n_gpu_layers if stats else None,
        "llama_tps": stats.tokens_per_second if stats else None,
        "llama_slots_active": stats.slots_active if stats else None,
        "models_count": len(models),
        "gpu_model": _gpu_info.model if _gpu_info else None,
        "vram_total_mb": _gpu_info.vram_total_mb if _gpu_info else None,
        "vram_used_mb": _gpu_info.vram_used_mb if _gpu_info else None,
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@app.get("/models")
async def list_models() -> list[dict]:
    from spouet_agent.model_manager import list_local_models, model_supports_tools
    if not _models_dir:
        return []
    models = list_local_models(_models_dir)
    return [
        {
            "name": m.name,
            "path": m.path,
            "size_bytes": m.size_bytes,
            "parameter_size": m.parameter_size,
            "quant": m.quant,
            "supports_tools": model_supports_tools(m.name),
        }
        for m in models
    ]


class DownloadRequest(BaseModel):
    hf_repo: str
    filename: str
    hf_token: str | None = None


@app.post("/models/download", status_code=status.HTTP_202_ACCEPTED)
async def start_download(req: DownloadRequest) -> dict:
    if not _models_dir:
        raise HTTPException(500, "models_dir not configured")
    global _download_status
    if _download_status.get("status") in ("starting", "downloading"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Un téléchargement est déjà en cours : {_download_status.get('filename')}",
        )
    _download_status = {"status": "starting", "repo": req.hf_repo, "filename": req.filename}
    asyncio.create_task(_download_task(req.hf_repo, req.filename, req.hf_token))
    return {"status": "accepted"}


@app.get("/models/download/status")
async def download_status() -> dict:
    return _download_status


class CheckRequest(BaseModel):
    hf_repo: str
    filename: str
    hf_token: str | None = None


@app.post("/models/check")
async def check_model(req: CheckRequest) -> dict:
    """Pré-vérifie qu'un fichier GGUF est compatible/téléchargeable (avant pull)."""
    from spouet_agent.model_manager import check_gguf

    return await check_gguf(req.hf_repo, req.filename, req.hf_token)


async def _download_task(hf_repo: str, filename: str, hf_token: str | None) -> None:
    global _download_status
    from spouet_agent.model_manager import download_model
    try:
        _download_status = {"status": "downloading", "repo": hf_repo, "filename": filename, "progress": 0}
        path = await download_model(hf_repo, filename, _models_dir, hf_token)  # type: ignore[arg-type]
        _download_status = {"status": "done", "path": str(path), "filename": filename}
    except Exception as e:
        _download_status = {"status": "error", "error": str(e)}


class LoadRequest(BaseModel):
    filename: str


def _resolve_model_path(filename: str) -> Path:
    """Résout `filename` dans _models_dir en bloquant tout path traversal.

    Le contrat est un nom de fichier simple (`Meta-Llama-3.1-8B-...gguf`).
    On refuse séparateurs, segments parents et chemins absolus.
    """
    if not _models_dir:
        raise HTTPException(500, "models_dir not configured")
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, f"Invalid filename {filename!r}")
    candidate = (_models_dir / filename).resolve()
    try:
        candidate.relative_to(_models_dir.resolve())
    except ValueError as exc:
        raise HTTPException(400, f"Filename escapes models dir: {filename!r}") from exc
    return candidate


@app.post("/models/load")
async def load_model(req: LoadRequest) -> dict:
    if not _models_dir or not _server:
        raise HTTPException(500, "server not initialized")
    model_path = _resolve_model_path(req.filename)
    if not model_path.exists():
        raise HTTPException(404, f"Model {req.filename!r} not found in models dir")

    # Concurrence : si un chargement est déjà en cours sur un autre modèle, on refuse.
    # Si c'est le même modèle qui est déjà loading, on retourne l'état tel quel.
    if _load_status["state"] == "loading":
        if _load_status.get("filename") == req.filename:
            return {"status": "loading", "filename": req.filename}
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Un chargement est déjà en cours pour {_load_status.get('filename')!r}",
        )

    from spouet_agent.capabilities import probe_capabilities
    from spouet_agent.llama_config import compute_optimal_config, get_model_size_bytes
    # Si capabilities n'a pas été injecté (anciens chemins), on les recalcule
    # à la volée pour rester compatible.
    caps = _capabilities or probe_capabilities()
    config = compute_optimal_config(
        caps=caps,
        ram_total_mb=_gpu_info.ram_total_mb if _gpu_info else None,
        model_size_bytes=get_model_size_bytes(model_path),
    )
    _load_status.update(
        state="loading",
        filename=req.filename,
        error=None,
        started_at=time.time(),
        ready_at=None,
    )
    asyncio.create_task(_load_task(model_path, config, req.filename))
    return {"status": "loading", "filename": req.filename}


@app.get("/load/status")
async def load_status() -> dict:
    """État du dernier chargement llama-server (loading/ready/error/idle)."""
    return dict(_load_status)


async def _load_task(model_path: Path, config: Any, filename: str) -> None:
    import typer
    async with _load_lock:
        try:
            await _server.start(model_path, config)
            _load_status.update(state="ready", error=None, ready_at=time.time())
            typer.echo(f"[agent-api] model {filename!r} ready")
        except Exception as e:
            err = f"{e}\n{traceback.format_exc()}"
            _load_status.update(state="error", error=str(e), ready_at=time.time())
            typer.echo(f"[agent-api] failed to load model: {err}", err=True)


@app.delete("/models/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_endpoint(filename: str) -> None:
    from spouet_agent.model_manager import delete_model
    model_path = _resolve_model_path(filename)
    if not model_path.exists():
        raise HTTPException(404, f"Model {filename!r} not found")
    delete_model(model_path)


# ---------------------------------------------------------------------------
# Diagnostic : dernières lignes du process llama-server
# ---------------------------------------------------------------------------

@app.get("/diag/llama")
async def diag_llama(n: int = 50) -> dict:
    """Dernières lignes émises par llama-server + erreur de démarrage éventuelle.

    Indispensable quand `/load/status` remonte `error`: permet au backend
    (et au frontend) d'afficher la cause sans accès SSH au node.
    """
    if not _server:
        raise HTTPException(500, "server not initialized")
    caps_payload = _capabilities.to_dict() if _capabilities is not None else None
    return {
        "running": _server.is_running(),
        "lines": _server.get_recent_logs(n),
        "last_startup_error": _server.get_last_startup_error(),
        "load_state": _load_status.get("state"),
        "load_error": _load_status.get("error"),
        "capabilities": caps_payload,
    }


@app.get("/capabilities")
async def get_capabilities() -> dict:
    """Capacités matérielles détectées (compute_class, gpu_kind, warnings…)."""
    if _capabilities is None:
        raise HTTPException(500, "capabilities not initialized")
    return _capabilities.to_dict()


# ---------------------------------------------------------------------------
# Config / restart
# ---------------------------------------------------------------------------

class LlamaConfigPatch(BaseModel):
    n_ctx: int | None = None
    n_gpu_layers: int | None = None
    n_batch: int | None = None
    n_ubatch: int | None = None
    n_threads: int | None = None
    n_threads_batch: int | None = None
    n_parallel: int | None = None


@app.patch("/config")
async def patch_config(patch: LlamaConfigPatch) -> dict:
    if not _server:
        raise HTTPException(500, "server not initialized")
    if not _server.is_running():
        raise HTTPException(409, "llama-server is not running — load a model first")
    from spouet_agent.llama_config import LlamaConfig
    current = _server._current_config
    if current is None:
        raise HTTPException(409, "No current config to patch")
    updated = LlamaConfig(
        n_ctx=patch.n_ctx if patch.n_ctx is not None else current.n_ctx,
        n_gpu_layers=patch.n_gpu_layers if patch.n_gpu_layers is not None else current.n_gpu_layers,
        n_batch=patch.n_batch if patch.n_batch is not None else current.n_batch,
        n_ubatch=patch.n_ubatch if patch.n_ubatch is not None else current.n_ubatch,
        n_threads=patch.n_threads if patch.n_threads is not None else current.n_threads,
        n_threads_batch=patch.n_threads_batch if patch.n_threads_batch is not None else current.n_threads_batch,
        n_parallel=patch.n_parallel if patch.n_parallel is not None else current.n_parallel,
    )
    asyncio.create_task(_restart_task(updated))
    return {"status": "restarting", "config": {
        "n_ctx": updated.n_ctx,
        "n_gpu_layers": updated.n_gpu_layers,
        "n_batch": updated.n_batch,
        "n_parallel": updated.n_parallel,
    }}


async def _restart_task(config: Any) -> None:
    import typer
    async with _load_lock:
        current_model = getattr(_server, "_current_model", None)
        if current_model is not None:
            _load_status.update(
                state="loading",
                filename=current_model.name,
                error=None,
                started_at=time.time(),
                ready_at=None,
            )
        try:
            await _server.restart(config=config)
            _load_status.update(state="ready", error=None, ready_at=time.time())
        except Exception as e:
            err = f"{e}\n{traceback.format_exc()}"
            _load_status.update(state="error", error=str(e), ready_at=time.time())
            typer.echo(f"[agent-api] failed to restart with new config: {err}", err=True)
