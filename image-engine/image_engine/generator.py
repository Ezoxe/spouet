"""Génération d'images via diffusers (Stable Diffusion / SDXL).

Le pipeline est chargé une seule fois (lazy ou préchargé) et réutilisé. Comme un
pipeline diffusers n'est pas thread-safe et qu'une inférence sature déjà le GPU
(ou le CPU), on sérialise les appels avec un verrou — même posture que le moteur
voix (`_infer_lock`).
"""

from __future__ import annotations

import io
import logging
import os
import threading
from typing import Any

from image_engine.config import settings

# diffusers/transformers lisent HF_HOME à l'import : on le fixe avant tout import
# de la lib (les imports lourds restent paresseux, dans les fonctions ci-dessous).
os.environ.setdefault("HF_HOME", settings.hf_home)

logger = logging.getLogger("image_engine.generator")

_pipe: Any = None
_load_lock = threading.Lock()
_infer_lock = threading.Lock()


def _torch_dtype() -> Any:
    import torch

    return {"float16": torch.float16, "bfloat16": torch.bfloat16, "float32": torch.float32}.get(
        settings.dtype, torch.float32
    )


def _load() -> Any:
    """Charge (une fois) le pipeline text2image et le place sur le device."""
    global _pipe
    if _pipe is not None:
        return _pipe
    with _load_lock:
        if _pipe is not None:
            return _pipe
        import torch  # noqa: F401
        from diffusers import AutoPipelineForText2Image

        logger.info("Chargement du modèle %s (device=%s, dtype=%s)…",
                    settings.model, settings.device, settings.dtype)
        kwargs: dict[str, Any] = {"torch_dtype": _torch_dtype()}
        if settings.device == "cuda":
            # variant fp16 quand le repo le publie : poids 2x plus légers.
            kwargs["variant"] = "fp16"
        try:
            pipe = AutoPipelineForText2Image.from_pretrained(settings.model, **kwargs)
        except Exception:  # noqa: BLE001 — repo sans variant fp16 => fallback sans variant
            kwargs.pop("variant", None)
            pipe = AutoPipelineForText2Image.from_pretrained(settings.model, **kwargs)

        pipe = pipe.to(settings.device)
        # Optimisations mémoire (sans coût qualité notable).
        try:
            pipe.enable_attention_slicing()
            if settings.device == "cuda":
                pipe.enable_vae_slicing()
        except Exception:  # noqa: BLE001
            pass
        # Coupe le safety checker : self-hosted, usage personnel, et il refuse
        # parfois des images légitimes (faux positifs) en ralentissant l'inférence.
        if hasattr(pipe, "safety_checker"):
            pipe.safety_checker = None
        _pipe = pipe
        logger.info("Modèle prêt.")
        return _pipe


def preload() -> None:
    _load()


def is_loaded() -> bool:
    return _pipe is not None


def _clamp_dim(value: int | None) -> int:
    try:
        v = int(value) if value else settings.default_size
    except (TypeError, ValueError):
        v = settings.default_size
    v = max(256, min(v, settings.max_dimension))
    return (v // 8) * 8  # SD exige des multiples de 8


def generate(
    prompt: str,
    *,
    negative_prompt: str | None = None,
    width: int | None = None,
    height: int | None = None,
    steps: int | None = None,
    guidance_scale: float | None = None,
    seed: int | None = None,
) -> bytes:
    """Génère une image et renvoie ses octets PNG."""
    import torch

    pipe = _load()
    w = _clamp_dim(width)
    h = _clamp_dim(height)
    try:
        n_steps = int(steps) if steps else settings.default_steps
    except (TypeError, ValueError):
        n_steps = settings.default_steps
    n_steps = max(1, min(n_steps, settings.max_steps))
    try:
        guidance = float(guidance_scale) if guidance_scale is not None else settings.default_guidance
    except (TypeError, ValueError):
        guidance = settings.default_guidance
    guidance = max(0.0, min(guidance, 20.0))

    generator = None
    if seed is not None:
        try:
            generator = torch.Generator(device=settings.device).manual_seed(int(seed))
        except (TypeError, ValueError):
            generator = None

    kwargs: dict[str, Any] = {
        "prompt": prompt,
        "width": w,
        "height": h,
        "num_inference_steps": n_steps,
        "guidance_scale": guidance,
    }
    if negative_prompt:
        kwargs["negative_prompt"] = negative_prompt
    if generator is not None:
        kwargs["generator"] = generator

    with _infer_lock:
        result = pipe(**kwargs)
    image = result.images[0]

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
