"""Paramètres llama.cpp-server optimaux selon le matériel détecté.

`compute_optimal_config` consomme un `NodeCapabilities` (source unique de
vérité hardware) et retourne une `LlamaConfig` prête à passer à llama-server.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from spouet_agent.capabilities import NodeCapabilities


@dataclass
class LlamaConfig:
    n_ctx: int = 8192
    n_gpu_layers: int = -1  # -1 = toutes les couches sur GPU
    n_batch: int = 512
    n_ubatch: int = 512
    n_threads: int | None = None  # None = auto (llama.cpp calcule)
    n_threads_batch: int | None = None  # None = identique à n_threads
    n_parallel: int = 1  # slots parallèles


# Au-delà de 16 threads, llama.cpp sature en synchro inter-threads sur CPU
# desktop/serveur courant — pas de gain, parfois perte. Surchargeable via
# SPOUET_MAX_THREADS pour les très gros CPU (EPYC/Threadripper) où le seuil
# utile diffère.
_DEFAULT_MAX_CPU_THREADS = 16


def _max_cpu_threads() -> int:
    """Plafond de threads CPU (env SPOUET_MAX_THREADS, défaut 16, borné 1..256)."""
    raw = os.environ.get("SPOUET_MAX_THREADS")
    if raw:
        try:
            v = int(raw.strip())
            if v >= 1:
                return min(256, v)
        except ValueError:
            pass
    return _DEFAULT_MAX_CPU_THREADS


def _estimate_kv_cache_mb(n_ctx: int, model_size_bytes: int | None) -> int:
    """Estimation grossière de la KV cache (MB), conservative (sur-estime).

    KV exacte = 2 (K+V) × n_ctx × n_layers × n_kv_heads × head_dim × 2 octets.
    Comme on n'a pas accès au header GGUF ici, on approxime via la taille du
    fichier. Mesures de référence (architectures GQA modernes, Llama 3.x / Qwen 2.5) :
      - Llama-70B-Q4 (40 GB) @ ctx 8192 → KV réelle ≈ 2.5 GB
      - Llama-8B-Q4 (5 GB)   @ ctx 8192 → KV réelle ≈ 1.0 GB
    Le ratio bytes_KV / (bytes_modèle × n_ctx) varie de 8e-6 (70B) à 2.5e-5 (8B).
    On retient 2e-5 — sur-estime un peu pour rester du côté sûr (n_ctx réduit
    mais OOM évité).
    """
    if not model_size_bytes:
        return 1024  # fallback prudent
    bytes_estimate = int(2.0e-5 * model_size_bytes * n_ctx)
    return max(256, bytes_estimate // (1024 * 1024))


def compute_optimal_config(
    caps: NodeCapabilities,
    ram_total_mb: int | None,
    model_size_bytes: int | None = None,
    model_n_layers: int | None = None,
) -> LlamaConfig:
    """Calcule les paramètres llama.cpp optimaux selon le hardware disponible.

    La décision GPU vs CPU est entièrement déléguée à `caps.compute_class` —
    plus de seuil VRAM ad-hoc. Cela évite qu'un iGPU détecté avec > 512 MB
    de mémoire partagée déclenche par erreur un n_gpu_layers != 0 sur un
    binaire CPU.

    `model_size_bytes` (optionnel) : taille du GGUF à charger, utilisée pour
    ajuster n_ctx en CPU et garantir que le KV cache + modèle tient en RAM.

    `model_n_layers` (optionnel) : nombre de couches du modèle (en-tête GGUF).
    Permet, sur GPU, un **offload partiel** quand le modèle ne tient pas en VRAM :
    au lieu de tout charger (n_gpu_layers=-1 → OOM), on calcule le nombre de
    couches qui rentre et on laisse le reste sur CPU. Si inconnu → -1 (tout GPU).
    """
    if caps.compute_class == "cpu":
        physical = caps.cpu_physical_cores
        max_threads = _max_cpu_threads()
        # Laisse au moins 1 cœur à l'OS, et plafonne au seuil utile pour llama.cpp.
        n_threads = max(1, min(max_threads, physical - 1 if physical > 2 else physical))

        # Le prompt processing (compute-bound) profite de l'hyperthreading,
        # contrairement à la génération token-par-token (memory-bound). On élargit
        # donc le pool de threads du batch jusqu'aux cœurs logiques (plafonné),
        # sans jamais descendre sous n_threads (défaut llama.cpp = identique).
        logical = os.cpu_count() or n_threads
        n_threads_batch = max(n_threads, min(max_threads, logical))

        ram_mb = ram_total_mb or 8192  # fallback raisonnable (au lieu de 4 GB)

        # En CPU, le modèle est mappé en mémoire (mmap). Si la taille du modèle
        # est connue, on borne n_ctx pour que (modèle + KV cache + ~2 GB OS)
        # tienne dans la RAM physique. On garde une marge stricte : sinon la
        # page cache va swapper et les perfs s'effondrent (10× plus lent).
        if model_size_bytes:
            model_mb = model_size_bytes // (1024 * 1024)
            # Budget restant pour KV cache + overhead llama + OS.
            budget_kv_mb = ram_mb - model_mb - 2048  # 2 GB réservés OS+agent

            if budget_kv_mb < 256:
                # Le modèle seul est plus gros que la RAM dispo : on tente
                # quand même avec ctx minimal — mmap permettra de fonctionner
                # via le page cache disque (lent mais possible).
                n_ctx = 2048
            else:
                # Cherche le plus grand n_ctx ≤ palier qui rentre dans le budget.
                for candidate in (16384, 8192, 4096, 2048):
                    if _estimate_kv_cache_mb(candidate, model_size_bytes) <= budget_kv_mb:
                        n_ctx = candidate
                        break
                else:
                    n_ctx = 2048
        else:
            # Sans info sur le modèle : paliers de RAM, conservateurs.
            if ram_mb >= 64000:
                n_ctx = 8192
            elif ram_mb >= 32000:
                n_ctx = 4096
            else:
                n_ctx = 2048

        return LlamaConfig(
            n_ctx=n_ctx,
            n_gpu_layers=0,
            n_batch=512,   # default llama.cpp — bon compromis throughput/mémoire
            n_ubatch=512,
            n_threads=n_threads,
            n_threads_batch=n_threads_batch,
            n_parallel=1,
        )

    vram = caps.vram_total_mb or 0

    # Tier de base selon la VRAM agrégée (multi-GPU : somme des cartes).
    if vram >= 80000:  # H100 80GB, A100 80GB
        cfg = LlamaConfig(n_ctx=131072, n_gpu_layers=-1, n_batch=4096, n_ubatch=4096, n_parallel=8)
    elif vram >= 40000:  # A100 40GB, 2×RTX 4090
        cfg = LlamaConfig(n_ctx=131072, n_gpu_layers=-1, n_batch=2048, n_ubatch=2048, n_parallel=4)
    elif vram >= 24000:  # RTX 3090, RTX 4090
        cfg = LlamaConfig(n_ctx=65536, n_gpu_layers=-1, n_batch=1024, n_ubatch=1024, n_parallel=2)
    elif vram >= 16000:  # RTX 4080, RTX 3080 Ti
        cfg = LlamaConfig(n_ctx=32768, n_gpu_layers=-1, n_batch=512, n_ubatch=512, n_parallel=2)
    elif vram >= 8000:   # RTX 4070, RTX 3070
        cfg = LlamaConfig(n_ctx=16384, n_gpu_layers=-1, n_batch=512, n_ubatch=512, n_parallel=1)
    elif vram >= 4000:   # RTX 3060, etc.
        cfg = LlamaConfig(n_ctx=8192, n_gpu_layers=-1, n_batch=256, n_ubatch=256, n_parallel=1)
    else:
        cfg = LlamaConfig(n_ctx=4096, n_gpu_layers=-1, n_batch=128, n_ubatch=128, n_parallel=1)

    # Offload partiel : si le modèle (poids + KV + overhead) dépasse la VRAM,
    # on ne charge sur GPU que le nombre de couches qui rentre, le reste reste
    # sur CPU. Sans ça, n_gpu_layers=-1 fait planter llama-server en OOM dès
    # qu'on charge un modèle plus gros que la carte (cas fréquent : 70B sur 24 GB).
    if model_size_bytes and vram > 0:
        fitted = _fit_gpu_layers(vram, model_size_bytes, cfg.n_ctx, model_n_layers)
        if fitted is not None:
            cfg.n_gpu_layers, cfg.n_ctx = fitted
            cfg.n_parallel = 1  # un seul slot quand on partage GPU/CPU

    return cfg


# Overhead VRAM hors couches (contexte CUDA, buffers de calcul, tenseurs non
# offloadables type embeddings/output). Marge prudente : mieux vaut offloader
# une couche de moins que risquer l'OOM.
_GPU_OVERHEAD_MB = 1024
# En offload partiel, le GPU est sous-dimensionné : on borne le contexte pour
# laisser de la VRAM aux couches (et parce que l'estimation KV grossit vite avec
# n_ctx). 8192 reste confortable pour du chat.
_PARTIAL_OFFLOAD_CTX = 8192


def _fit_gpu_layers(
    vram_mb: int,
    model_size_bytes: int,
    n_ctx: int,
    model_n_layers: int | None,
) -> tuple[int, int] | None:
    """Couches GPU + n_ctx ajustés, ou None si tout tient (→ garder -1, ctx tier).

    - modèle + KV + overhead ≤ VRAM → None (offload total, n_gpu_layers=-1).
    - sinon, si n_layers connu → (couches qui rentrent 0..n_layers, ctx borné).
    - sinon (n_layers inconnu) → None (repli sûr : on garde -1, comportement
      historique ; llama.cpp gérera ou échouera comme avant).
    """
    model_mb = model_size_bytes // (1024 * 1024)
    kv_full_mb = _estimate_kv_cache_mb(n_ctx, model_size_bytes)
    if model_mb + kv_full_mb + _GPU_OVERHEAD_MB <= vram_mb:
        return None  # tient entièrement → offload total
    if not model_n_layers or model_n_layers <= 0:
        return None  # inconnu → repli historique (-1)

    # Partage GPU/CPU : on borne le contexte pour libérer de la VRAM aux couches.
    fit_ctx = min(n_ctx, _PARTIAL_OFFLOAD_CTX)
    kv_mb = _estimate_kv_cache_mb(fit_ctx, model_size_bytes)
    budget = vram_mb - kv_mb - _GPU_OVERHEAD_MB
    if budget <= 0:
        return 0, fit_ctx  # même une couche ne tient pas → tout CPU
    per_layer_mb = max(1, model_mb // model_n_layers)
    layers = max(0, min(model_n_layers, budget // per_layer_mb))
    return layers, fit_ctx


def get_model_size_bytes(model_path: Path) -> int | None:
    """Taille du fichier modèle en octets, ou None si introuvable."""
    try:
        return model_path.stat().st_size
    except OSError:
        return None
