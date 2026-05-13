"""Paramètres llama.cpp-server optimaux selon le matériel détecté.

`compute_optimal_config` consomme un `NodeCapabilities` (source unique de
vérité hardware) et retourne une `LlamaConfig` prête à passer à llama-server.
"""

from __future__ import annotations

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
    n_parallel: int = 1  # slots parallèles


# Au-delà de 16 threads, llama.cpp sature en synchro inter-threads sur CPU
# desktop/serveur courant — pas de gain, parfois perte.
_MAX_CPU_THREADS = 16


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
) -> LlamaConfig:
    """Calcule les paramètres llama.cpp optimaux selon le hardware disponible.

    La décision GPU vs CPU est entièrement déléguée à `caps.compute_class` —
    plus de seuil VRAM ad-hoc. Cela évite qu'un iGPU détecté avec > 512 MB
    de mémoire partagée déclenche par erreur un n_gpu_layers != 0 sur un
    binaire CPU.

    `model_size_bytes` (optionnel) : taille du GGUF à charger, utilisée pour
    ajuster n_ctx en CPU et garantir que le KV cache + modèle tient en RAM.
    """
    if caps.compute_class == "cpu":
        physical = caps.cpu_physical_cores
        # Laisse au moins 1 cœur à l'OS, et plafonne au seuil utile pour llama.cpp.
        n_threads = max(1, min(_MAX_CPU_THREADS, physical - 1 if physical > 2 else physical))

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
            n_parallel=1,
        )

    vram = caps.vram_total_mb or 0

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


def get_model_size_bytes(model_path: Path) -> int | None:
    """Taille du fichier modèle en octets, ou None si introuvable."""
    try:
        return model_path.stat().st_size
    except OSError:
        return None
