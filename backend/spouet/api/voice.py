"""Routes voix : transcription (STT) et synthèse (TTS).

Proxy authentifié vers le microservice voice-engine. Le front capture l'audio
(MediaRecorder), POST `/transcribe`, puis lit l'audio renvoyé par `/speak`.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from spouet.api.deps import CurrentUser
from spouet.core.config import settings
from spouet.core.logging import get_logger
from spouet.voice import client as voice_client

router = APIRouter()
logger = get_logger(__name__)


class TranscriptOut(BaseModel):
    text: str


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    voice: str | None = None


@router.get("/health")
async def voice_health(user: CurrentUser) -> dict:
    """État du moteur voix (utilisé par le panneau Santé système)."""
    if not settings.voice_enabled:
        return {"enabled": False, "ok": False}
    try:
        info = await voice_client.health()
        return {"enabled": True, "ok": True, **info}
    except voice_client.VoiceEngineError as e:
        return {"enabled": True, "ok": False, "error": str(e)}


@router.post("/transcribe", response_model=TranscriptOut)
async def transcribe(
    audio: UploadFile,
    user: CurrentUser,
    language: str | None = Form(default=None),
) -> TranscriptOut:
    if not settings.voice_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Voix désactivée")
    raw = await audio.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Audio vide")
    if len(raw) > settings.voice_max_audio_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Audio trop volumineux")
    try:
        text = await voice_client.transcribe(
            raw,
            filename=audio.filename or "audio.webm",
            content_type=audio.content_type or "application/octet-stream",
            language=language or settings.voice_language or None,
        )
    except voice_client.VoiceEngineError as e:
        logger.warning("voice.transcribe_failed", error=str(e))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return TranscriptOut(text=text)


@router.post("/speak")
async def speak(payload: SpeakIn, user: CurrentUser) -> Response:
    if not settings.voice_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Voix désactivée")
    try:
        wav = await voice_client.synthesize(
            payload.text, voice=payload.voice or settings.voice_tts_voice or None
        )
    except voice_client.VoiceEngineError as e:
        logger.warning("voice.speak_failed", error=str(e))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return Response(content=wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})
