"""Tests pour compute_optimal_config — verrouille les invariants critiques :
- CPU-only → n_gpu_layers = 0 (sinon llama-server crash)
- iGPU forcé en CPU → n_gpu_layers = 0
- GPU dédié → n_gpu_layers = -1 (toutes les couches)
"""

from __future__ import annotations

from spouet_agent.capabilities import NodeCapabilities
from spouet_agent.llama_config import compute_optimal_config


def _caps(
    compute_class: str = "cpu",
    gpu_kind: str = "none",
    vram_mb: int | None = None,
    cores: int = 8,
) -> NodeCapabilities:
    return NodeCapabilities(
        compute_class=compute_class,  # type: ignore[arg-type]
        gpu_kind=gpu_kind,  # type: ignore[arg-type]
        gpu_model=None if compute_class == "cpu" else "GPU",
        vram_total_mb=vram_mb,
        cpu_model="i5",
        cpu_physical_cores=cores,
        cpu_features=["avx2"],
        llama_variant="cpu-avx2" if compute_class == "cpu" else "cuda-cu12",
        force_cpu=False,
    )


def test_cpu_only_forbids_gpu_layers():
    cfg = compute_optimal_config(caps=_caps("cpu"), ram_total_mb=16384)
    assert cfg.n_gpu_layers == 0, "Invariant CPU : n_gpu_layers DOIT être 0"
    assert cfg.n_threads is not None
    assert cfg.n_threads <= 16  # plafond MAX_CPU_THREADS


def test_force_cpu_caps_yields_zero_gpu_layers():
    """Même si caps a une VRAM ancienne dans le payload (cas de bug observé)."""
    caps = NodeCapabilities(
        compute_class="cpu",
        gpu_kind="none",
        gpu_model=None,
        vram_total_mb=8192,  # piège : VRAM non None mais CPU-only
        cpu_model="Ryzen",
        cpu_physical_cores=8,
        cpu_features=["avx2"],
        llama_variant="cpu-avx2",
        force_cpu=True,
    )
    cfg = compute_optimal_config(caps=caps, ram_total_mb=32768)
    assert cfg.n_gpu_layers == 0


def test_cuda_dgpu_uses_all_layers():
    cfg = compute_optimal_config(
        caps=_caps(compute_class="cuda", gpu_kind="dgpu", vram_mb=24576),
        ram_total_mb=32768,
    )
    assert cfg.n_gpu_layers == -1
    assert cfg.n_ctx >= 32768  # config GPU généreuse


def test_cpu_ctx_scales_with_ram():
    """Sans modèle, n_ctx doit grandir avec la RAM."""
    cfg_low = compute_optimal_config(caps=_caps("cpu"), ram_total_mb=16000)
    cfg_mid = compute_optimal_config(caps=_caps("cpu"), ram_total_mb=32000)
    cfg_high = compute_optimal_config(caps=_caps("cpu"), ram_total_mb=64000)
    assert cfg_low.n_ctx <= cfg_mid.n_ctx <= cfg_high.n_ctx


def test_cpu_ctx_respects_model_size_budget():
    """Sur 16 GB RAM, un modèle de 13 GB ne doit pas demander un n_ctx énorme."""
    # 13 GB modèle ≈ 13 * 1024^3
    cfg = compute_optimal_config(
        caps=_caps("cpu"),
        ram_total_mb=16384,
        model_size_bytes=13 * 1024**3,
    )
    # Budget restant = 16 - 13 - 2 (réservé OS) = 1 GB → ctx minimal 2048
    assert cfg.n_ctx == 2048


def test_cpu_threads_capped_by_max():
    """Pour un node 64 cœurs, plafond à 16 threads (sinon llama.cpp sature)."""
    cfg = compute_optimal_config(caps=_caps("cpu", cores=64), ram_total_mb=128000)
    assert cfg.n_threads == 16


def test_cpu_threads_leaves_one_core_for_os():
    """8 cœurs physiques → 7 threads pour llama, 1 pour l'OS."""
    cfg = compute_optimal_config(caps=_caps("cpu", cores=8), ram_total_mb=32000)
    assert cfg.n_threads == 7
