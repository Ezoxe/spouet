"""API image du node-agent (port dédié, défaut 8083).

Plan de données de la génération d'images, appelé par le backend Spouet :

    GET  /health        → état (available/device/model/ready)
    GET  /status        → idem + état du pull/load
    POST /pull          → télécharge un modèle HF (async, façon GGUF)
    GET  /pull/status   → progrès du téléchargement
    POST /load          → met un modèle en mémoire (async)
    GET  /load/status   → état du chargement (idle/loading/ready/error)
    POST /generate      → JSON {prompt, ...} → image/png

Séparé de l'API de contrôle (8765, plan llama.cpp) : même découpage que
llama-server (8080 inférence) vs agent-api (8765 contrôle).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from spouet_agent import image_gen

app = FastAPI(title="spouet-agent image API", docs_url=None, redoc_url=None)

_load_state: dict[str, Any] = {"state": "idle", "model": None, "error": None}
_load_lock = asyncio.Lock()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", **image_gen.status()}


@app.get("/status")
async def get_status() -> dict[str, Any]:
    return {**image_gen.status(), "load": dict(_load_state)}


# ---------------------------------------------------------------------------
# Pull (téléchargement des poids)
# ---------------------------------------------------------------------------


class PullRequest(BaseModel):
    model: str = Field(min_length=1)
    hf_token: str | None = None


@app.post("/pull", status_code=status.HTTP_202_ACCEPTED)
async def pull(req: PullRequest) -> dict[str, str]:
    if not image_gen.images_available():
        raise HTTPException(503, "extra image non installé sur ce node (spouet-agent[images])")
    cur = image_gen.pull_status()
    if cur.get("status") == "downloading":
        raise HTTPException(409, f"téléchargement déjà en cours: {cur.get('model')}")
    asyncio.create_task(_pull_task(req.model, req.hf_token))
    return {"status": "accepted", "model": req.model}


async def _pull_task(model: str, hf_token: str | None) -> None:
    try:
        await run_in_threadpool(image_gen.pull, model, hf_token)
    except Exception:  # noqa: BLE001 — l'état d'erreur est déjà dans _pull_status
        pass


@app.get("/pull/status")
async def pull_status() -> dict[str, Any]:
    return image_gen.pull_status()


class CheckRequest(BaseModel):
    model: str = Field(min_length=1)
    hf_token: str | None = None


@app.post("/pull/check")
async def pull_check(req: CheckRequest) -> dict[str, Any]:
    """Pré-vérifie qu'un repo HF est chargeable par le moteur d'images (avant pull)."""
    if not image_gen.images_available():
        raise HTTPException(503, "extra image non installé sur ce node (spouet-agent[images])")
    return await run_in_threadpool(image_gen.check_compatibility, req.model, req.hf_token)


@app.get("/models")
async def list_models() -> list[dict[str, Any]]:
    return await run_in_threadpool(image_gen.list_models)


class DeleteModelRequest(BaseModel):
    model: str = Field(min_length=1)


@app.post("/models/delete")
async def delete_model(req: DeleteModelRequest) -> dict[str, str]:
    await run_in_threadpool(image_gen.delete_model, req.model)
    return {"status": "deleted", "model": req.model}


# ---------------------------------------------------------------------------
# Load (mise en mémoire du modèle actif)
# ---------------------------------------------------------------------------


class LoadRequest(BaseModel):
    model: str | None = None


@app.post("/load")
async def load(req: LoadRequest) -> dict[str, Any]:
    if not image_gen.images_available():
        raise HTTPException(503, "extra image non installé sur ce node (spouet-agent[images])")
    if _load_state["state"] == "loading":
        raise HTTPException(409, f"chargement déjà en cours: {_load_state.get('model')}")
    target = req.model or image_gen.current_model() or image_gen.default_model()
    _load_state.update(state="loading", model=target, error=None, started_at=time.time())
    asyncio.create_task(_load_task(target))
    return {"status": "loading", "model": target}


async def _load_task(model: str) -> None:
    async with _load_lock:
        try:
            active = await run_in_threadpool(image_gen.load, model)
            _load_state.update(state="ready", model=active, error=None, ready_at=time.time())
        except Exception as e:  # noqa: BLE001
            _load_state.update(state="error", error=str(e), ready_at=time.time())


@app.get("/load/status")
async def load_status() -> dict[str, Any]:
    return dict(_load_state)


# ---------------------------------------------------------------------------
# Génération
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    model: str | None = None
    negative_prompt: str | None = Field(default=None, max_length=2000)
    width: int | None = Field(default=None, ge=64, le=2048)
    height: int | None = Field(default=None, ge=64, le=2048)
    steps: int | None = Field(default=None, ge=1, le=150)
    guidance_scale: float | None = Field(default=None, ge=0.0, le=30.0)
    seed: int | None = None


@app.post("/generate")
async def generate(req: GenerateRequest) -> Response:
    if not image_gen.images_available():
        raise HTTPException(503, "extra image non installé sur ce node (spouet-agent[images])")
    try:
        png = await run_in_threadpool(
            image_gen.generate,
            req.prompt,
            model=req.model,
            negative_prompt=req.negative_prompt,
            width=req.width,
            height=req.height,
            steps=req.steps,
            guidance_scale=req.guidance_scale,
            seed=req.seed,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"échec génération: {e}") from e
    # Reflète le modèle réellement actif après une éventuelle auto-load.
    if _load_state.get("state") != "ready" and image_gen.is_loaded():
        _load_state.update(state="ready", model=image_gen.current_model(), error=None)
    return Response(content=png, media_type="image/png")
