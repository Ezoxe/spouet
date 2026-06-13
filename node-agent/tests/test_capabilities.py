"""Tests pour la détection des capabilities — focus sur les cas qui ont causé
des bugs en prod (iGPU AMD pris pour dGPU, force_cpu, NVIDIA sans libcuda…)."""

from __future__ import annotations

import pytest

from spouet_agent import capabilities as caps_mod


@pytest.fixture(autouse=True)
def _clear_force_cpu(monkeypatch):
    monkeypatch.delenv("SPOUET_FORCE_CPU", raising=False)


def _stub_cpu(monkeypatch, model: str = "Intel(R) Core(TM) i5-9300H", cores: int = 4):
    monkeypatch.setattr(caps_mod, "_detect_cpu", lambda: (model, cores))
    monkeypatch.setattr(caps_mod, "_detect_cpu_features", lambda: ["avx2", "fma", "sse4_2"])


def test_force_cpu_short_circuits_detection(monkeypatch):
    """SPOUET_FORCE_CPU=1 ne doit même pas tenter nvidia-smi."""
    _stub_cpu(monkeypatch)
    monkeypatch.setenv("SPOUET_FORCE_CPU", "1")
    # Si _probe_nvidia était appelé, on lèverait — vérifie qu'on n'y arrive pas
    monkeypatch.setattr(caps_mod, "_probe_nvidia", lambda *a, **kw: pytest.fail("ne doit pas être appelé"))

    caps = caps_mod.probe_capabilities()
    assert caps.compute_class == "cpu"
    assert caps.gpu_kind == "none"
    assert caps.force_cpu is True
    assert caps.llama_variant == "cpu-avx2"


def test_cpu_only_machine(monkeypatch):
    """Aucun GPU détectable → compute_class=cpu, llama_variant aligné aux flags."""
    _stub_cpu(monkeypatch)
    monkeypatch.setattr(caps_mod, "_probe_nvidia", lambda *a, **kw: None)
    monkeypatch.setattr(caps_mod, "_probe_rocm", lambda *a, **kw: None)
    monkeypatch.setattr(caps_mod, "_probe_drm", lambda *a, **kw: None)

    caps = caps_mod.probe_capabilities()
    assert caps.compute_class == "cpu"
    assert caps.gpu_kind == "none"
    assert caps.vram_total_mb is None
    assert caps.llama_variant == "cpu-avx2"


def test_nvidia_dgpu_dominates(monkeypatch):
    """nvidia-smi + libcuda OK → compute_class=cuda, dgpu."""
    _stub_cpu(monkeypatch, model="AMD Ryzen 9 7950X", cores=16)
    monkeypatch.setattr(caps_mod, "_probe_nvidia", lambda notes, warnings: ("NVIDIA RTX 4090", 24576, 1))

    caps = caps_mod.probe_capabilities()
    assert caps.compute_class == "cuda"
    assert caps.gpu_kind == "dgpu"
    assert caps.gpu_model == "NVIDIA RTX 4090"
    assert caps.vram_total_mb == 24576
    assert caps.gpu_count == 1
    assert caps.llama_variant.startswith("cuda-cu")


def test_nvidia_multi_gpu_aggregates_vram(monkeypatch):
    """2 cartes NVIDIA → VRAM sommée + gpu_count=2 (parsing réel de _probe_nvidia)."""
    _stub_cpu(monkeypatch, model="AMD Ryzen 9 7950X", cores=16)
    monkeypatch.setattr(caps_mod.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(
        caps_mod.subprocess,
        "check_output",
        lambda *a, **kw: "NVIDIA RTX 4090, 24576\nNVIDIA RTX 4090, 24576\n",
    )
    monkeypatch.setattr(caps_mod, "_cuda_libs_available", lambda notes: True)

    caps = caps_mod.probe_capabilities()
    assert caps.compute_class == "cuda"
    assert caps.gpu_count == 2
    assert caps.vram_total_mb == 49152
    assert caps.gpu_model == "NVIDIA RTX 4090 ×2"


def test_nvidia_without_libcuda_falls_back_to_cpu(monkeypatch):
    """GPU détecté par nvidia-smi mais drivers absents → CPU + warning."""
    _stub_cpu(monkeypatch)

    def _nv(notes, warnings):
        # Simule le cas réel : _probe_nvidia détecte un GPU mais retourne None
        # car libcuda absente — il ajoute un warning lui-même.
        warnings.append("GPU NVIDIA détecté mais libcuda.so introuvable")
        return None

    monkeypatch.setattr(caps_mod, "_probe_nvidia", _nv)
    monkeypatch.setattr(caps_mod, "_probe_rocm", lambda *a, **kw: None)
    monkeypatch.setattr(caps_mod, "_probe_drm", lambda *a, **kw: None)

    caps = caps_mod.probe_capabilities()
    assert caps.compute_class == "cpu"
    assert any("libcuda" in w for w in caps.warnings)


def test_amd_apu_classed_as_igpu_not_dgpu(monkeypatch):
    """L'APU AMD (Phoenix etc.) doit retomber sur CPU — bug racine corrigé."""
    _stub_cpu(monkeypatch, model="AMD Ryzen 7 7840HS", cores=8)
    monkeypatch.setattr(caps_mod, "_probe_nvidia", lambda *a, **kw: None)
    monkeypatch.setattr(caps_mod, "_probe_rocm", lambda *a, **kw: None)
    monkeypatch.setattr(
        caps_mod,
        "_probe_drm",
        lambda notes, warnings: ("AMD Radeon Graphics (Phoenix)", 8192, "igpu"),
    )

    caps = caps_mod.probe_capabilities()
    assert caps.compute_class == "cpu", "APU AMD doit forcer CPU"
    assert caps.gpu_kind == "none"
    assert caps.vram_total_mb is None
    assert any("iGPU" in w or "APU" in w for w in caps.warnings)


def test_amd_dgpu_classed_as_rocm(monkeypatch):
    """Un dGPU AMD détecté via DRM → rocm/dgpu, pas iGPU."""
    _stub_cpu(monkeypatch)
    monkeypatch.setattr(caps_mod, "_probe_nvidia", lambda *a, **kw: None)
    monkeypatch.setattr(caps_mod, "_probe_rocm", lambda *a, **kw: None)
    monkeypatch.setattr(
        caps_mod,
        "_probe_drm",
        lambda notes, warnings: ("AMD Radeon RX 7900 XTX", 24576, "dgpu"),
    )

    caps = caps_mod.probe_capabilities()
    assert caps.compute_class == "rocm"
    assert caps.gpu_kind == "dgpu"
    assert caps.vram_total_mb == 24576


def test_pick_cpu_variant_avx_levels():
    assert caps_mod._pick_cpu_variant(["avx512f", "avx2", "fma"]) == "cpu-avx512"
    assert caps_mod._pick_cpu_variant(["avx2", "fma"]) == "cpu-avx2"
    assert caps_mod._pick_cpu_variant(["avx", "sse4_2"]) == "cpu-avx"
    assert caps_mod._pick_cpu_variant(["sse4_2"]) == "cpu"
    assert caps_mod._pick_cpu_variant([]) == "cpu"


def test_env_truthy():
    assert caps_mod._env_truthy("1")
    assert caps_mod._env_truthy("true")
    assert caps_mod._env_truthy("YES")
    assert caps_mod._env_truthy("on")
    assert not caps_mod._env_truthy("0")
    assert not caps_mod._env_truthy("")
    assert not caps_mod._env_truthy(None)
    assert not caps_mod._env_truthy("false")
