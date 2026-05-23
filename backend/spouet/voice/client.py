"""Client httpx vers le microservice `voice-engine`.

Le backend ne fait *que* proxifier : l'auth/quotas sont gérés côté API Spouet,
voice-engine reste un service interne sans authentification propre.
"""

from __future__ import annotations

from typing import Any

import httpx

from spouet.core.config import settings
from spouet.core.logging import get_logger

logger = get_logger(__name__)


class VoiceEngineError(RuntimeError):
    """voice-engine injoignable ou a renvoyé une erreur."""


def _base() -> str:
    return settings.voice_engine_url.rstrip("/")


async def transcribe(
    audio: bytes,
    *,
    filename: str,
    content_type: str,
    language: str | None = None,
) -> str:
    """Envoie l'audio à voice-engine et renvoie le texte transcrit."""
    files = {"audio": (filename, audio, content_type)}
    data: dict[str, str] = {}
    if language:
        data["language"] = language
    try:
        async with httpx.AsyncClient(timeout=settings.voice_timeout_s) as client:
            resp = await client.post(f"{_base()}/stt", files=files, data=data)
    except httpx.HTTPError as e:
        raise VoiceEngineError(f"voice-engine injoignable: {e}") from e
    if resp.status_code != 200:
        raise VoiceEngineError(f"STT {resp.status_code}: {resp.text[:200]}")
    return str((resp.json() or {}).get("text") or "").strip()


async def synthesize(text: str, *, voice: str | None = None) -> bytes:
    """Renvoie un WAV synthétisé par Piper."""
    payload: dict[str, str] = {"text": text}
    if voice:
        payload["voice"] = voice
    try:
        async with httpx.AsyncClient(timeout=settings.voice_timeout_s) as client:
            resp = await client.post(f"{_base()}/tts", json=payload)
    except httpx.HTTPError as e:
        raise VoiceEngineError(f"voice-engine injoignable: {e}") from e
    if resp.status_code != 200:
        raise VoiceEngineError(f"TTS {resp.status_code}: {resp.text[:200]}")
    return resp.content


async def health() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_base()}/health")
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise VoiceEngineError(f"voice-engine injoignable: {e}") from e
    return resp.json()
