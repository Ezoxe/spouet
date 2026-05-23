"""Configuration du microservice voix (variables d'environnement).

Service autonome : pas de préfixe `SPOUET_` ici (c'est le docker-compose qui
mappe les variables `SPOUET_*` du serveur vers ces noms courts).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


@dataclass(frozen=True)
class Settings:
    # --- STT (faster-whisper) ---
    # Modèles : tiny | base | small | medium | large-v3 (+ variantes .en).
    # `small` = bon compromis FR/CPU. `medium` plus précis mais ~3x plus lent.
    whisper_model: str = os.getenv("WHISPER_MODEL", "small")
    # cpu | cuda. Sur GPU NVIDIA, mettre `cuda` + compute_type `float16`.
    whisper_device: str = os.getenv("WHISPER_DEVICE", "cpu")
    # int8 (CPU, rapide) | int8_float16 | float16 (GPU) | float32.
    whisper_compute_type: str = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    # Langue par défaut ("" => détection auto par Whisper).
    whisper_language: str = os.getenv("WHISPER_LANGUAGE", "fr")
    # beam_size : 1 = rapide (interactif), 5 = plus précis.
    whisper_beam_size: int = int(os.getenv("WHISPER_BEAM_SIZE", "5"))

    # --- TTS (Piper) ---
    # Voix au format `<locale>-<nom>-<qualité>` (cf. rhasspy/piper-voices).
    # Voix FR dispo : fr_FR-siwis-medium, fr_FR-upmc-medium, fr_FR-tom-medium…
    piper_voice: str = os.getenv("PIPER_VOICE", "fr_FR-siwis-medium")
    piper_repo: str = os.getenv("PIPER_REPO", "rhasspy/piper-voices")
    # Répertoire (volume) où sont mis en cache les modèles Piper téléchargés.
    piper_data_dir: str = os.getenv("PIPER_DATA_DIR", "/data/piper")

    # Précharger les modèles au démarrage (sinon lazy au 1er appel).
    preload: bool = _flag("MODELS_PRELOAD", True)


settings = Settings()
