"""Génération d'images sur le node (diffusers / Stable Diffusion).

Tourne *dans* le node-agent — c'est la machine GPU. Les dépendances lourdes
(torch / diffusers) sont un extra optionnel (`spouet-agent[images]`) : un node
CPU sans l'extra n'expose simplement pas la capacité image.

Gestion explicite du modèle (façon GGUF) : `pull()` télécharge les poids HF dans
le cache du node, `load()` met le modèle actif en mémoire, `generate()` produit
un PNG. L'inférence est sérialisée (verrou) et exécutée hors de l'event loop par
l'appelant (threadpool), pour ne jamais bloquer le heartbeat.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("spouet_agent.image_gen")

# État partagé (lu par l'API image + le heartbeat).
_pipe: Any = None
_current_model: str | None = None
# Modèle configuré pour ce node (via --image-model) : cible par défaut du load
# et valeur remontée au heartbeat avant tout chargement. None => défaut device.
_configured_model: str | None = None
_load_lock = threading.Lock()
_infer_lock = threading.Lock()
_pull_status: dict[str, Any] = {"status": "idle"}

# Modèles par défaut selon le device (cf. AutoPipelineForText2Image).
_DEFAULT_MODEL_CUDA = "stabilityai/sdxl-turbo"
_DEFAULT_MODEL_CPU = "stabilityai/sd-turbo"


def images_available() -> bool:
    """True si l'extra image (torch + diffusers) est installé sur ce node."""
    import importlib.util

    return (
        importlib.util.find_spec("torch") is not None
        and importlib.util.find_spec("diffusers") is not None
    )


def device() -> str:
    """cuda si un GPU NVIDIA est exploitable, sinon cpu (forçable IMAGE_DEVICE)."""
    forced = (os.getenv("IMAGE_DEVICE") or "").strip().lower()
    if forced in ("cpu", "cuda"):
        return forced
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


def default_model() -> str:
    if _configured_model:
        return _configured_model
    return _DEFAULT_MODEL_CUDA if device() == "cuda" else _DEFAULT_MODEL_CPU


def set_configured(model: str | None) -> None:
    global _configured_model
    _configured_model = (model or "").strip() or None


def reported_model() -> str | None:
    """Modèle à remonter au heartbeat : chargé si dispo, sinon configuré."""
    return _current_model or _configured_model


def _dtype() -> Any:
    import torch

    forced = (os.getenv("IMAGE_DTYPE") or "").strip().lower()
    table = {"float16": torch.float16, "bfloat16": torch.bfloat16, "float32": torch.float32}
    if forced in table:
        return table[forced]
    return torch.float16 if device() == "cuda" else torch.float32


def current_model() -> str | None:
    return _current_model


def is_loaded() -> bool:
    return _pipe is not None


def pull_status() -> dict[str, Any]:
    st = dict(_pull_status)
    if st.get("status") == "downloading":
        with _pull_progress_lock:
            done = _pull_progress["downloaded"]
            total = _pull_progress["total"]
        st["downloaded_mb"] = round(done / 1e6, 1)
        st["total_mb"] = round(total / 1e6, 1) if total else None
        st["percent"] = round(done / total * 100, 1) if total else None
        if _pull_started_at:
            st["elapsed_s"] = round(time.time() - _pull_started_at, 1)
    return st


def status() -> dict[str, Any]:
    return {
        "available": images_available(),
        "device": device(),
        "model": _current_model,
        "ready": _pipe is not None,
        "pull": dict(_pull_status),
    }


# ---------------------------------------------------------------------------
# Téléchargement (pull) — coarse status, façon GGUF
# ---------------------------------------------------------------------------


# Compteur d'octets partagé pour la barre de progression (alimenté par le tqdm
# custom passé à snapshot_download, lu par pull_status()).
_pull_progress = {"downloaded": 0, "total": 0}
_pull_progress_lock = threading.Lock()
_pull_started_at: float = 0.0


def _progress_tqdm_class():  # type: ignore[no-untyped-def]
    """Sous-classe tqdm qui agrège octets téléchargés / total sur tous les fichiers."""
    from tqdm.auto import tqdm as _base

    class _ProgressTqdm(_base):  # type: ignore[misc]
        def __init__(self, *a, **k):  # type: ignore[no-untyped-def]
            super().__init__(*a, **k)
            with _pull_progress_lock:
                if self.total:
                    _pull_progress["total"] += int(self.total)

        def update(self, n=1):  # type: ignore[no-untyped-def]
            with _pull_progress_lock:
                _pull_progress["downloaded"] += int(n or 0)
            return super().update(n)

    return _ProgressTqdm


def pull(model: str, hf_token: str | None = None) -> None:
    """Télécharge (bloquant) les poids HF de `model` dans le cache du node.

    À lancer en threadpool. Met à jour `_pull_status` (octets + %) au fil de l'eau.
    """
    global _pull_status, _pull_started_at
    from huggingface_hub import snapshot_download

    with _pull_progress_lock:
        _pull_progress["downloaded"] = 0
        _pull_progress["total"] = 0
    _pull_started_at = time.time()
    _pull_status = {"status": "downloading", "model": model, "started_at": _pull_started_at}
    try:
        snapshot_download(
            repo_id=model,
            token=hf_token or None,
            # Évite les doublons de poids : on prend les safetensors + configs.
            ignore_patterns=["*.ckpt", "*.pt", "*.onnx", "*.msgpack"],
            tqdm_class=_progress_tqdm_class(),
        )
        _pull_status = {"status": "done", "model": model}
    except Exception as e:  # noqa: BLE001
        logger.exception("pull failed for %s", model)
        _pull_status = {"status": "error", "model": model, "error": str(e)}
        raise


# ---------------------------------------------------------------------------
# Chargement du pipeline
# ---------------------------------------------------------------------------


def load(model: str | None = None) -> str:
    """Charge le pipeline pour `model` (ou le défaut). Renvoie le modèle actif."""
    global _pipe, _current_model
    target = model or _current_model or default_model()
    with _load_lock:
        if _pipe is not None and _current_model == target:
            return target
        import torch  # noqa: F401
        from diffusers import AutoPipelineForText2Image

        dev = device()
        logger.info("Chargement du modèle image %s (device=%s)…", target, dev)
        kwargs: dict[str, Any] = {"torch_dtype": _dtype()}
        if dev == "cuda":
            kwargs["variant"] = "fp16"
        try:
            pipe = AutoPipelineForText2Image.from_pretrained(target, **kwargs)
        except Exception:  # noqa: BLE001 — repo sans variant fp16 => sans variant
            kwargs.pop("variant", None)
            pipe = AutoPipelineForText2Image.from_pretrained(target, **kwargs)

        pipe = pipe.to(dev)
        try:
            pipe.enable_attention_slicing()
            if dev == "cuda":
                pipe.enable_vae_slicing()
        except Exception:  # noqa: BLE001
            pass
        if hasattr(pipe, "safety_checker"):
            pipe.safety_checker = None

        # Libère l'ancien pipeline avant de basculer.
        _pipe = pipe
        _current_model = target
        logger.info("Modèle image %s prêt.", target)
        return target


def unload() -> None:
    global _pipe, _current_model
    with _load_lock:
        _pipe = None
        _current_model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Génération
# ---------------------------------------------------------------------------


def _max_dimension() -> int:
    try:
        return int(os.getenv("IMAGE_MAX_DIMENSION", "1024"))
    except ValueError:
        return 1024


def _default_size() -> int:
    env = os.getenv("IMAGE_DEFAULT_SIZE")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    return 1024 if device() == "cuda" else 512


def _clamp_dim(value: int | None) -> int:
    try:
        v = int(value) if value else _default_size()
    except (TypeError, ValueError):
        v = _default_size()
    v = max(256, min(v, _max_dimension()))
    return (v // 8) * 8


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
    """Génère une image et renvoie ses octets PNG. À lancer en threadpool."""
    import torch

    if _pipe is None:
        load()
    pipe = _pipe
    assert pipe is not None

    w = _clamp_dim(width)
    h = _clamp_dim(height)
    try:
        n_steps = int(steps) if steps else 4
    except (TypeError, ValueError):
        n_steps = 4
    n_steps = max(1, min(n_steps, 50))
    try:
        guidance = float(guidance_scale) if guidance_scale is not None else 0.0
    except (TypeError, ValueError):
        guidance = 0.0
    guidance = max(0.0, min(guidance, 20.0))

    generator = None
    if seed is not None:
        try:
            generator = torch.Generator(device=device()).manual_seed(int(seed))
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
