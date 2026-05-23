"""API HTTP du microservice voix.

Endpoints (consommés uniquement par le backend Spouet, jamais exposés au LAN) :

    GET  /health           -> état + modèles chargés
    POST /stt              -> multipart `audio` (+ `language`) -> {"text": "..."}
    POST /tts              -> JSON {"text", "voice"?} -> audio/wav
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from voice_engine import __version__, stt, tts
from voice_engine.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("voice_engine")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.preload:
        # Précharge en threadpool pour ne pas bloquer le démarrage de l'event loop.
        logger.info("Préchargement des modèles…")
        try:
            await run_in_threadpool(stt.preload)
            await run_in_threadpool(tts.preload)
        except Exception:  # noqa: BLE001
            # On ne tue pas le service : un modèle peut être préchargé au 1er appel.
            logger.exception("Préchargement partiel des modèles (continuera à la demande).")
    yield


app = FastAPI(title="Spouet Voice Engine", version=__version__, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "stt": {"model": settings.whisper_model, "ready": stt.is_loaded()},
        "tts": {"voice": settings.piper_voice, "ready": tts.is_loaded()},
    }


@app.post("/stt")
async def transcribe(
    audio: UploadFile = File(...),
    language: str | None = Form(default=None),
) -> dict[str, str]:
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Audio vide")
    try:
        text = await run_in_threadpool(
            stt.transcribe, data, language or settings.whisper_language
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Échec de la transcription")
        raise HTTPException(status_code=500, detail=f"Échec STT: {e}") from e
    return {"text": text}


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    voice: str | None = None


@app.post("/tts")
async def speak(req: TtsRequest) -> Response:
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Texte vide")
    try:
        wav = await run_in_threadpool(tts.synthesize, req.text, req.voice)
    except Exception as e:  # noqa: BLE001
        logger.exception("Échec de la synthèse")
        raise HTTPException(status_code=500, detail=f"Échec TTS: {e}") from e
    return Response(content=wav, media_type="audio/wav")
