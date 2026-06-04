"""Configuration du microservice de génération d'images.

Service autonome : pas de préfixe `SPOUET_` ici (c'est le docker-compose qui
mappe les variables `SPOUET_*` du serveur vers ces noms courts).

Le device est auto-détecté au démarrage (CUDA si disponible, sinon CPU) sauf si
`IMAGE_DEVICE` est forcé. Le modèle par défaut s'adapte au device : un modèle
« turbo » léger sur CPU (utilisable), un SDXL-Turbo sur GPU (rapide + qualité).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _auto_device() -> str:
    """cuda si un GPU NVIDIA est exploitable, sinon cpu."""
    forced = (os.getenv("IMAGE_DEVICE") or "").strip().lower()
    if forced in ("cpu", "cuda"):
        return forced
    try:
        import torch  # import paresseux : torch est lourd

        if torch.cuda.is_available():
            return "cuda"
    except Exception:  # noqa: BLE001 — pas de torch / pas de GPU => CPU
        pass
    return "cpu"


# Modèles par défaut selon le device. SDXL-Turbo = distillé, 1-4 steps,
# guidance 0 => très rapide sur GPU. SD-Turbo = 512px, viable sur CPU.
_DEFAULT_MODEL_CUDA = "stabilityai/sdxl-turbo"
_DEFAULT_MODEL_CPU = "stabilityai/sd-turbo"


@dataclass(frozen=True)
class Settings:
    device: str = _auto_device()
    # dtype : float16 sur GPU (2x moins de VRAM), float32 sur CPU (fp16 non géré).
    dtype: str = os.getenv("IMAGE_DTYPE", "") or ("float16" if _auto_device() == "cuda" else "float32")
    # Modèle Hugging Face (text2image). Vide => défaut adapté au device.
    model: str = os.getenv("IMAGE_MODEL", "") or (
        _DEFAULT_MODEL_CUDA if _auto_device() == "cuda" else _DEFAULT_MODEL_CPU
    )
    # Cache HuggingFace des poids (volume persistant).
    hf_home: str = os.getenv("HF_HOME", "/data/hf")

    # Bornes de génération (garde-fous mémoire / temps).
    max_dimension: int = int(os.getenv("IMAGE_MAX_DIMENSION", "1024"))
    max_steps: int = int(os.getenv("IMAGE_MAX_STEPS", "50"))
    # Defaults appliqués quand le client ne précise rien. Les modèles « turbo »
    # tournent en très peu de steps avec guidance 0.
    default_steps: int = int(os.getenv("IMAGE_DEFAULT_STEPS", "4"))
    default_guidance: float = float(os.getenv("IMAGE_DEFAULT_GUIDANCE", "0.0"))
    default_size: int = int(os.getenv("IMAGE_DEFAULT_SIZE", "0")) or (
        1024 if _auto_device() == "cuda" else 512
    )

    # Précharger le modèle au démarrage (sinon lazy au 1er appel).
    preload: bool = _flag("MODELS_PRELOAD", True)


settings = Settings()
