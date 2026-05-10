"""Mini FastAPI — plan de contrôle du node-agent (port 8765).

Endpoints appelés par le backend Spouet pour piloter llama.cpp :
  GET  /status              → état + stats llama-server
  GET  /models              → liste GGUF locaux
  POST /models/download     → lance téléchargement HuggingFace async
  GET  /models/download/status → progrès du dernier téléchargement
  POST /models/load         → change le modèle actif (redémarre llama-server)
  DELETE /models/{filename} → supprime un GGUF
  PATCH /config             → change les params llama.cpp (redémarre llama-server)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="spouet-agent control API", docs_url=None, redoc_url=None)

# Références injectées depuis main.py au démarrage
_server: Any = None  # LlamaServer instance
_models_dir: Path | None = None
_gpu_info: Any = None  # GpuInfo
_download_queue: asyncio.Queue[dict] = asyncio.Queue()
_download_status: dict = {}


def init(server: Any, models_dir: Path, gpu_info: Any) -> None:
    global _server, _models_dir, _gpu_info
    _server = server
    _models_dir = models_dir
    _gpu_info = gpu_info


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
    _download_status = {"status": "starting", "repo": req.hf_repo, "filename": req.filename}
    asyncio.create_task(_download_task(req.hf_repo, req.filename, req.hf_token))
    return {"status": "accepted"}


@app.get("/models/download/status")
async def download_status() -> dict:
    return _download_status


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


@app.post("/models/load")
async def load_model(req: LoadRequest) -> dict:
    if not _models_dir or not _server:
        raise HTTPException(500, "server not initialized")
    model_path = _models_dir / req.filename
    if not model_path.exists():
        raise HTTPException(404, f"Model {req.filename!r} not found in models dir")
    from spouet_agent.llama_config import compute_optimal_config
    config = compute_optimal_config(
        gpu_model=_gpu_info.model if _gpu_info else None,
        vram_total_mb=_gpu_info.vram_total_mb if _gpu_info else None,
        ram_total_mb=_gpu_info.ram_total_mb if _gpu_info else None,
    )
    asyncio.create_task(_load_task(model_path, config))
    return {"status": "loading", "filename": req.filename}


async def _load_task(model_path: Path, config: Any) -> None:
    try:
        await _server.start(model_path, config)
    except Exception as e:
        import typer
        typer.echo(f"[agent-api] failed to load model: {e}", err=True)


@app.delete("/models/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_endpoint(filename: str) -> None:
    if not _models_dir:
        raise HTTPException(500, "models_dir not configured")
    from spouet_agent.model_manager import delete_model
    model_path = _models_dir / filename
    if not model_path.exists():
        raise HTTPException(404, f"Model {filename!r} not found")
    delete_model(model_path)


# ---------------------------------------------------------------------------
# Config / restart
# ---------------------------------------------------------------------------

class LlamaConfigPatch(BaseModel):
    n_ctx: int | None = None
    n_gpu_layers: int | None = None
    n_batch: int | None = None
    n_ubatch: int | None = None
    n_threads: int | None = None
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
    try:
        await _server.restart(config=config)
    except Exception as e:
        import typer
        typer.echo(f"[agent-api] failed to restart with new config: {e}", err=True)
