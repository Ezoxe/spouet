"""API HTTP du microservice de génération d'images.

Endpoints (consommés uniquement par le backend Spouet, jamais exposés au LAN) :

    GET  /health      -> état + modèle / device
    POST /generate    -> JSON {prompt, ...} -> image/png
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from image_engine import __version__, generator
from image_engine.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("image_engine")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.preload:
        logger.info("Préchargement du modèle d'images…")
        try:
            await run_in_threadpool(generator.preload)
        except Exception:  # noqa: BLE001 — on ne tue pas le service : load au 1er appel
            logger.exception("Préchargement échoué (réessai à la demande).")
    yield


app = FastAPI(title="Spouet Image Engine", version=__version__, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model": settings.model,
        "device": settings.device,
        "dtype": settings.dtype,
        "ready": generator.is_loaded(),
    }


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str | None = Field(default=None, max_length=2000)
    width: int | None = Field(default=None, ge=64, le=2048)
    height: int | None = Field(default=None, ge=64, le=2048)
    steps: int | None = Field(default=None, ge=1, le=150)
    guidance_scale: float | None = Field(default=None, ge=0.0, le=30.0)
    seed: int | None = None


@app.post("/generate")
async def generate(req: GenerateRequest) -> Response:
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt vide")
    try:
        png = await run_in_threadpool(
            generator.generate,
            req.prompt,
            negative_prompt=req.negative_prompt,
            width=req.width,
            height=req.height,
            steps=req.steps,
            guidance_scale=req.guidance_scale,
            seed=req.seed,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Échec de la génération d'image")
        raise HTTPException(status_code=500, detail=f"Échec génération: {e}") from e
    return Response(content=png, media_type="image/png")
