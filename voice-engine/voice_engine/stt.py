"""Reconnaissance vocale (Speech-To-Text) via faster-whisper.

Le modèle est chargé paresseusement puis gardé en mémoire. L'inférence est
sérialisée par un lock : le service est mono-utilisateur (self-hosted), inutile
de paralléliser des transcriptions CPU-bound qui se voleraient les cœurs.
"""

from __future__ import annotations

import io
import logging
import threading

from faster_whisper import WhisperModel

from voice_engine.config import settings

logger = logging.getLogger("voice_engine.stt")

_model: WhisperModel | None = None
_load_lock = threading.Lock()
_infer_lock = threading.Lock()


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        with _load_lock:
            if _model is None:
                logger.info(
                    "Chargement du modèle Whisper '%s' (device=%s, compute=%s)…",
                    settings.whisper_model,
                    settings.whisper_device,
                    settings.whisper_compute_type,
                )
                _model = WhisperModel(
                    settings.whisper_model,
                    device=settings.whisper_device,
                    compute_type=settings.whisper_compute_type,
                )
                logger.info("Modèle Whisper prêt.")
    return _model


def is_loaded() -> bool:
    return _model is not None


def preload() -> None:
    _get_model()


def transcribe(audio_bytes: bytes, language: str | None) -> str:
    """Transcrit un flux audio (n'importe quel format décodable par ffmpeg/PyAV).

    `language` vide ou None => détection automatique.
    """
    model = _get_model()  # acquiert/libère _load_lock en interne
    lang = (language or "").strip() or None
    with _infer_lock:
        segments, _info = model.transcribe(
            io.BytesIO(audio_bytes),
            language=lang,
            beam_size=settings.whisper_beam_size,
            vad_filter=True,
        )
        return "".join(seg.text for seg in segments).strip()
