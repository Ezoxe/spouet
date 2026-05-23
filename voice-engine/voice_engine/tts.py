"""Synthèse vocale (Text-To-Speech) via Piper.

Les modèles de voix sont téléchargés à la demande depuis HuggingFace
(`rhasspy/piper-voices`) et mis en cache dans un volume persistant, puis gardés
chargés en mémoire (un `PiperVoice` par nom de voix).
"""

from __future__ import annotations

import io
import logging
import threading
import wave

from huggingface_hub import hf_hub_download
from piper import PiperVoice

from voice_engine.config import settings

logger = logging.getLogger("voice_engine.tts")

_voices: dict[str, PiperVoice] = {}
_load_lock = threading.Lock()
_infer_lock = threading.Lock()


def _voice_to_hf_paths(voice: str) -> tuple[str, str]:
    """`fr_FR-siwis-medium` -> (`fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx`, …json)."""
    parts = voice.split("-")
    if len(parts) < 3:
        raise ValueError(
            f"Nom de voix invalide: {voice!r} (attendu <locale>-<nom>-<qualité>, "
            "ex. fr_FR-siwis-medium)"
        )
    locale, name, quality = parts[0], parts[1], parts[2]
    lang = locale.split("_")[0]
    base = f"{lang}/{locale}/{name}/{quality}/{voice}"
    return f"{base}.onnx", f"{base}.onnx.json"


def _get_voice(voice: str | None) -> PiperVoice:
    name = (voice or settings.piper_voice).strip()
    cached = _voices.get(name)
    if cached is not None:
        return cached
    with _load_lock:
        cached = _voices.get(name)
        if cached is not None:
            return cached
        onnx_rel, json_rel = _voice_to_hf_paths(name)
        logger.info("Téléchargement / chargement de la voix Piper '%s'…", name)
        onnx_path = hf_hub_download(
            repo_id=settings.piper_repo, filename=onnx_rel, cache_dir=settings.piper_data_dir
        )
        config_path = hf_hub_download(
            repo_id=settings.piper_repo, filename=json_rel, cache_dir=settings.piper_data_dir
        )
        pv = PiperVoice.load(onnx_path, config_path=config_path)
        _voices[name] = pv
        logger.info("Voix Piper '%s' prête.", name)
        return pv


def is_loaded() -> bool:
    return bool(_voices)


def preload() -> None:
    _get_voice(None)


def synthesize(text: str, voice: str | None = None) -> bytes:
    """Synthétise `text` et renvoie un WAV (PCM 16-bit mono) complet en mémoire."""
    pv = _get_voice(voice)
    buf = io.BytesIO()
    with _infer_lock:
        with wave.open(buf, "wb") as wav_file:
            pv.synthesize(text, wav_file)
    return buf.getvalue()
