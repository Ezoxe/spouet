"""Paramètres llama.cpp-server optimaux selon le matériel détecté."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class LlamaConfig:
    n_ctx: int = 8192
    n_gpu_layers: int = -1  # -1 = toutes les couches sur GPU
    n_batch: int = 512
    n_ubatch: int = 512
    n_threads: int | None = None  # None = auto (llama.cpp calcule)
    n_parallel: int = 1  # slots parallèles


def compute_optimal_config(
    gpu_model: str | None,
    vram_total_mb: int | None,
    ram_total_mb: int | None,
) -> LlamaConfig:
    """Calcule les paramètres llama.cpp optimaux selon le hardware disponible."""
    has_gpu = (
        gpu_model is not None
        and gpu_model not in ("CPU", "")
        and vram_total_mb is not None
        and vram_total_mb > 512
    )

    if not has_gpu:
        n_cores = os.cpu_count() or 4
        n_threads = max(1, n_cores - 1)
        ram_mb = ram_total_mb or 4096
        # KV cache CPU = 2 × ctx × n_layers × n_kv_heads × head_dim × 2 octets.
        # Sur un gros modèle (≥ 14B) le cache peut dépasser la RAM dispo si ctx est grand.
        # Règle conservatrice : laisser ≥ 4 GB pour le cache + OS + agent.
        if ram_mb >= 64000:
            n_ctx = 8192
        elif ram_mb >= 32000:
            n_ctx = 4096
        else:
            n_ctx = 2048   # 16–31 GB : budget serré avec les gros modèles
        return LlamaConfig(
            n_ctx=n_ctx,
            n_gpu_layers=0,
            n_batch=128,
            n_ubatch=128,
            n_threads=n_threads,
            n_parallel=1,
        )

    vram = vram_total_mb or 0

    if vram >= 80000:  # H100 80GB, A100 80GB
        return LlamaConfig(n_ctx=131072, n_gpu_layers=-1, n_batch=4096, n_ubatch=4096, n_parallel=8)
    elif vram >= 40000:  # A100 40GB, 2×RTX 4090
        return LlamaConfig(n_ctx=131072, n_gpu_layers=-1, n_batch=2048, n_ubatch=2048, n_parallel=4)
    elif vram >= 24000:  # RTX 3090, RTX 4090
        return LlamaConfig(n_ctx=65536, n_gpu_layers=-1, n_batch=1024, n_ubatch=1024, n_parallel=2)
    elif vram >= 16000:  # RTX 4080, RTX 3080 Ti
        return LlamaConfig(n_ctx=32768, n_gpu_layers=-1, n_batch=512, n_ubatch=512, n_parallel=2)
    elif vram >= 8000:   # RTX 4070, RTX 3070
        return LlamaConfig(n_ctx=16384, n_gpu_layers=-1, n_batch=512, n_ubatch=512, n_parallel=1)
    elif vram >= 4000:   # RTX 3060, etc.
        return LlamaConfig(n_ctx=8192, n_gpu_layers=-1, n_batch=256, n_ubatch=256, n_parallel=1)
    else:
        return LlamaConfig(n_ctx=4096, n_gpu_layers=-1, n_batch=128, n_ubatch=128, n_parallel=1)
