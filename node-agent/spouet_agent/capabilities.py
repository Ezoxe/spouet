"""Source de vérité unique pour le hardware du node.

Centralise toute la détection (GPU dédié vs iGPU vs CPU, features CPU, variante
de binaire llama.cpp à installer). L'agent calcule cet objet une fois au boot,
le sérialise dans le heartbeat, et il sert ensuite à choisir la config
llama-server, à valider les params runtime, et à diagnostiquer côté admin.

Conçu pour remplacer la triple détection éparpillée (`install.sh`, `gpu.py`,
`llama_server._detect_gpu_type`) — un seul code, testable.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

ComputeClass = Literal["cpu", "cuda", "rocm"]
GpuKind = Literal["none", "igpu", "dgpu"]


# Familles d'APU AMD à classer en iGPU (mémoire partagée RAM, pas utilisable
# par un build CPU de llama.cpp même si /sys/class/drm expose > 4 GiB).
# Liste basée sur les noms exposés via amdgpu product_name / marketing_name.
_AMD_APU_HINTS = (
    "phoenix",     # Ryzen 7040 (Phoenix 1/2)
    "hawk point",  # Ryzen 8040
    "strix",       # Ryzen AI 300 (Strix Point / Halo)
    "rembrandt",   # Ryzen 6000
    "raphael",     # Ryzen 7000 desktop (iGPU RDNA2 minimaliste)
    "cezanne",     # Ryzen 5000G
    "renoir",      # Ryzen 4000G
    "mendocino",   # Ryzen 7020
    "lucienne",
    "barcelo",
    "van gogh",    # Steam Deck APU
    "raven",       # Ryzen 2200G/2400G
    "picasso",     # Ryzen 3000G
    "dali",
    # gfx*-integrated patterns
    "gfx90c",
    "gfx1036",
    "gfx1037",
    "gfx1103",
    "gfx1150",
    "gfx1151",
)


@dataclass
class NodeCapabilities:
    """Capacités matérielles détectées au boot du node-agent."""

    compute_class: ComputeClass
    gpu_kind: GpuKind
    gpu_model: str | None
    vram_total_mb: int | None
    cpu_model: str | None
    cpu_physical_cores: int
    cpu_features: list[str]
    llama_variant: str
    force_cpu: bool
    # Nombre de GPU dédiés exploitables (0 si CPU/iGPU). `vram_total_mb` est la
    # VRAM AGRÉGÉE (somme de toutes les cartes) sur un node multi-GPU.
    gpu_count: int = 0
    warnings: list[str] = field(default_factory=list)
    # Diagnostic libre (ex: chemins libcuda trouvés, raison de classification iGPU)
    detection_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def is_gpu_usable(self) -> bool:
        return self.compute_class != "cpu"


# ---------------------------------------------------------------------------
# Détection
# ---------------------------------------------------------------------------


def probe_capabilities() -> NodeCapabilities:
    """Calcule les capabilities du node. Idempotent, sans effet de bord.

    Ordre :
      1. SPOUET_FORCE_CPU=1 → court-circuit CPU
      2. nvidia-smi + libcuda.so présent → cuda/dgpu
      3. rocm-smi disponible → rocm/dgpu (si OK)
      4. sysfs DRM amdgpu → dGPU AMD ou iGPU/APU (classé selon product_name + vis_vram)
      5. fallback → cpu/none
    """
    warnings: list[str] = []
    notes: list[str] = []

    cpu_model, physical = _detect_cpu()
    cpu_features = _detect_cpu_features()

    force_cpu = _env_truthy(os.environ.get("SPOUET_FORCE_CPU"))
    if force_cpu:
        notes.append("SPOUET_FORCE_CPU=1 — détection GPU désactivée")
        return NodeCapabilities(
            compute_class="cpu",
            gpu_kind="none",
            gpu_model=None,
            vram_total_mb=None,
            cpu_model=cpu_model,
            cpu_physical_cores=physical,
            cpu_features=cpu_features,
            llama_variant=_pick_cpu_variant(cpu_features),
            force_cpu=True,
            warnings=warnings,
            detection_notes=notes,
        )

    # 1. NVIDIA
    nv = _probe_nvidia(notes, warnings)
    if nv is not None:
        gpu_model, vram_mb, gpu_count = nv
        return NodeCapabilities(
            compute_class="cuda",
            gpu_kind="dgpu",
            gpu_model=gpu_model,
            vram_total_mb=vram_mb,
            cpu_model=cpu_model,
            cpu_physical_cores=physical,
            cpu_features=cpu_features,
            llama_variant=_pick_cuda_variant(notes),
            force_cpu=False,
            gpu_count=gpu_count,
            warnings=warnings,
            detection_notes=notes,
        )

    # 2. ROCm CLI
    rocm = _probe_rocm(notes, warnings)
    if rocm is not None:
        gpu_model, vram_mb = rocm
        return NodeCapabilities(
            compute_class="rocm",
            gpu_kind="dgpu",
            gpu_model=gpu_model,
            vram_total_mb=vram_mb,
            cpu_model=cpu_model,
            cpu_physical_cores=physical,
            cpu_features=cpu_features,
            llama_variant="rocm",
            force_cpu=False,
            gpu_count=1,
            warnings=warnings,
            detection_notes=notes,
        )

    # 3. sysfs DRM (AMD sans rocm-smi)
    drm = _probe_drm(notes, warnings)
    if drm is not None:
        gpu_model, vram_mb, kind = drm
        if kind == "dgpu":
            return NodeCapabilities(
                compute_class="rocm",
                gpu_kind="dgpu",
                gpu_model=gpu_model,
                vram_total_mb=vram_mb,
                cpu_model=cpu_model,
                cpu_physical_cores=physical,
                cpu_features=cpu_features,
                llama_variant="rocm",
                force_cpu=False,
                gpu_count=1,
                warnings=warnings,
                detection_notes=notes,
            )
        # iGPU détecté : on bascule en CPU mais on garde l'info dans les notes
        notes.append(f"iGPU AMD détecté ({gpu_model}) → CPU forcé (UMA non utilisable)")
        warnings.append(f"iGPU/APU AMD ignoré ({gpu_model}) : utilise SPOUET_FORCE_CPU=1 pour silencer")

    # 4. Fallback CPU
    return NodeCapabilities(
        compute_class="cpu",
        gpu_kind="none",
        gpu_model=None,
        vram_total_mb=None,
        cpu_model=cpu_model,
        cpu_physical_cores=physical,
        cpu_features=cpu_features,
        llama_variant=_pick_cpu_variant(cpu_features),
        force_cpu=False,
        warnings=warnings,
        detection_notes=notes,
    )


# ---------------------------------------------------------------------------
# Helpers de détection
# ---------------------------------------------------------------------------


def _env_truthy(v: str | None) -> bool:
    if v is None:
        return False
    return v.strip().lower() in ("1", "true", "yes", "on")


def _detect_cpu() -> tuple[str | None, int]:
    """Retourne (model_name, physical_cores)."""
    model: str | None = None
    physical = 1

    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                text = f.read()
            cores_per_socket: int | None = None
            sockets: set[str] = set()
            for line in text.splitlines():
                if line.startswith("model name") and model is None:
                    model = line.split(":", 1)[1].strip()
                elif line.startswith("physical id"):
                    sockets.add(line.split(":", 1)[1].strip())
                elif line.startswith("cpu cores") and cores_per_socket is None:
                    cores_per_socket = int(line.split(":", 1)[1].strip())
            if cores_per_socket and sockets:
                physical = cores_per_socket * len(sockets)
            elif cores_per_socket:
                physical = cores_per_socket
        except Exception:
            pass

    if model is None:
        model = platform.processor() or None

    if physical <= 1:
        try:
            import psutil  # type: ignore[import-untyped]

            p = psutil.cpu_count(logical=False)
            if p and p > 0:
                physical = int(p)
        except Exception:
            pass
        if physical <= 1:
            logical = os.cpu_count() or 1
            physical = max(1, logical // 2) if logical > 1 else logical

    return model, physical


def _detect_cpu_features() -> list[str]:
    """Lit /proc/cpuinfo flags (Linux) ou retourne une liste vide ailleurs."""
    if platform.system() != "Linux":
        return []
    flags_of_interest = {
        "sse2", "sse3", "ssse3", "sse4_1", "sse4_2",
        "avx", "avx2", "fma",
        "avx512f", "avx512bw", "avx512dq", "avx512vl", "avx512vnni",
        "f16c", "amx_int8", "amx_bf16",
    }
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("flags") or line.startswith("Features"):
                    parts = set(line.split(":", 1)[1].strip().split())
                    return sorted(parts & flags_of_interest)
    except Exception:
        pass
    return []


def _pick_cpu_variant(features: list[str]) -> str:
    s = set(features)
    if "avx512f" in s:
        return "cpu-avx512"
    if "avx2" in s:
        return "cpu-avx2"
    if "avx" in s:
        return "cpu-avx"
    return "cpu"


def _pick_cuda_variant(notes: list[str]) -> str:
    cuda_ver = "12"
    try:
        r = subprocess.run(
            ["nvcc", "--version"], capture_output=True, text=True, timeout=5
        )
        m = re.search(r"release (\d+)", r.stdout)
        if m:
            cuda_ver = m.group(1)
            notes.append(f"nvcc release {cuda_ver}")
    except (OSError, subprocess.SubprocessError):
        notes.append("nvcc absent — variante cuda-cu12 par défaut")
    return f"cuda-cu{cuda_ver}"


def _probe_nvidia(
    notes: list[str], warnings: list[str]
) -> tuple[str, int, int] | None:
    """Vérifie nvidia-smi ET la présence de libcuda.so (runtime utilisable).

    Multi-GPU : lit TOUTES les cartes. Retourne (modèle, vram_totale_agrégée_mb,
    nombre_de_cartes). Le modèle est celui de la 1re carte, suffixé ` ×N` si N>1
    (llama.cpp exploite par défaut toutes les cartes visibles).
    """
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None

    names: list[str] = []
    vram_total = 0
    for line in out.strip().splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            vram_total += int(parts[1])
        except ValueError:
            continue
        names.append(parts[0])

    if not names:
        return None

    count = len(names)
    gpu_name = names[0] if count == 1 else f"{names[0]} ×{count}"

    if not _cuda_libs_available(notes):
        warnings.append(
            f"GPU NVIDIA détecté ({gpu_name}) mais libcuda.so introuvable — "
            "fallback CPU. Installe les drivers CUDA pour activer le GPU."
        )
        return None
    if count > 1:
        notes.append(f"NVIDIA multi-GPU : {count} cartes, VRAM agrégée {vram_total} MB")
    else:
        notes.append(f"NVIDIA OK : {gpu_name} {vram_total} MB")
    return gpu_name, vram_total, count


def _cuda_libs_available(notes: list[str]) -> bool:
    try:
        r = subprocess.run(
            ["ldconfig", "-p"], capture_output=True, text=True, timeout=5
        )
        if "libcuda.so" in r.stdout:
            notes.append("libcuda.so trouvée via ldconfig")
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    for path in ["/usr/local/cuda/lib64", "/usr/lib/x86_64-linux-gnu", "/usr/lib64"]:
        try:
            if any(Path(path).glob("libcuda.so*")):
                notes.append(f"libcuda.so trouvée dans {path}")
                return True
        except Exception:
            pass
    return False


def _probe_rocm(
    notes: list[str], warnings: list[str]
) -> tuple[str, int] | None:
    """Tente rocm-smi pour un GPU AMD avec ROCm installé."""
    if not shutil.which("rocm-smi"):
        return None
    try:
        out = subprocess.check_output(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--csv"],
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    model: str | None = None
    total_b: int | None = None
    for line in out.splitlines():
        low = line.lower()
        if "card series" in low or "device name" in low:
            parts = line.split(",")
            if len(parts) >= 2:
                model = parts[1].strip()
        if "vram total" in low:
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip().isdigit():
                total_b = int(parts[1].strip())
    if model and total_b:
        notes.append(f"ROCm OK : {model} {total_b // (1024 * 1024)} MB")
        return model, total_b // (1024 * 1024)
    warnings.append("rocm-smi présent mais payload illisible — fallback DRM/CPU")
    return None


def _probe_drm(
    notes: list[str], warnings: list[str]
) -> tuple[str, int | None, GpuKind] | None:
    """Lit /sys/class/drm pour distinguer dGPU AMD vs APU iGPU.

    Retourne (model, vram_mb, kind). `kind` est "dgpu" ou "igpu".
    """
    import glob

    try:
        candidates = sorted(glob.glob("/sys/class/drm/card*/device"))
    except Exception:
        return None

    for card_path in candidates:
        card = Path(card_path)
        # Vérifie qu'on est bien sur amdgpu (pas i915, nouveau, etc.)
        uevent_path = card / "uevent"
        driver = ""
        try:
            for line in uevent_path.read_text().splitlines():
                if line.startswith("DRIVER="):
                    driver = line.split("=", 1)[1].strip().lower()
                    break
        except Exception:
            driver = ""
        if driver != "amdgpu":
            continue

        product = _read_first_existing(
            card, ("product_name", "marketing_name", "label", "device_name")
        )
        # mem_info_*_vram_total — sur APU ces fichiers existent mais représentent
        # de la RAM système réservée.
        total_b = _read_int_path(card / "mem_info_vram_total")
        vis_total = _read_int_path(card / "mem_info_vis_vram_total")
        if total_b is None or total_b == 0:
            continue

        # Heuristique APU :
        #   - product matchant un nom d'APU AMD connu → iGPU
        #   - OU vis_vram == total et total < 16 GiB (signature mémoire partagée
        #     car la "vram visible" est toute la "vram" déclarée)
        product_low = (product or "").lower()
        looks_like_apu = any(hint in product_low for hint in _AMD_APU_HINTS)
        signature_shared = (
            vis_total is not None and vis_total == total_b and total_b < 16 * 1024**3
        )
        # Et l'ancien filtre 4 GiB reste utile pour les APU sans nom détecté.
        very_small = total_b < 4 * 1024**3

        kind: GpuKind
        if looks_like_apu or signature_shared or very_small:
            kind = "igpu"
            notes.append(
                f"amdgpu={product!r} total={total_b // (1024**2)}MB "
                f"apu_hint={looks_like_apu} shared_sig={signature_shared} small={very_small}"
            )
        else:
            kind = "dgpu"
            notes.append(
                f"amdgpu={product!r} total={total_b // (1024**2)}MB classé dGPU"
            )

        gpu_name = product or "AMD GPU"
        return gpu_name, total_b // (1024**2), kind

    return None


def _read_first_existing(base: Path, names: tuple[str, ...]) -> str | None:
    for n in names:
        p = base / n
        try:
            val = p.read_text().strip()
            if val:
                return val
        except Exception:
            continue
    return None


def _read_int_path(p: Path) -> int | None:
    try:
        return int(p.read_text().strip())
    except Exception:
        return None
