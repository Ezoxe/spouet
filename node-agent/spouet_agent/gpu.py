"""Détection GPU et VRAM (NVIDIA et AMD)."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GpuInfo:
    model: str | None
    vram_total_mb: int | None
    vram_used_mb: int | None
    ram_total_mb: int | None
    ram_used_mb: int | None
    disk_total_mb: int | None
    disk_used_mb: int | None


def _get_ram_and_disk() -> tuple[int | None, int | None, int | None, int | None]:
    ram_total_mb: int | None = None
    ram_used_mb: int | None = None
    disk_total_mb: int | None = None
    disk_used_mb: int | None = None

    if platform.system() == "Windows":
        try:
            import psutil  # type: ignore[import-untyped]
            mem = psutil.virtual_memory()
            ram_total_mb = mem.total // (1024 * 1024)
            ram_used_mb = mem.used // (1024 * 1024)
        except Exception:
            pass
    else:
        try:
            with open("/proc/meminfo") as f:
                meminfo = f.read()
            total_kb = available_kb = 0
            for line in meminfo.splitlines():
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available_kb = int(line.split()[1])
            if total_kb > 0:
                ram_total_mb = total_kb // 1024
            if total_kb > 0 and available_kb > 0:
                ram_used_mb = (total_kb - available_kb) // 1024
        except Exception:
            pass

    try:
        root = "C:\\" if platform.system() == "Windows" else "/"
        usage = shutil.disk_usage(root)
        disk_total_mb = usage.total // (1024 * 1024)
        disk_used_mb = usage.used // (1024 * 1024)
    except Exception:
        pass

    return ram_total_mb, ram_used_mb, disk_total_mb, disk_used_mb

def probe_gpu() -> GpuInfo:
    """Tente nvidia-smi puis rocm-smi puis sysfs DRM. Retourne le CPU sans VRAM si rien trouvé."""
    ram_total, ram_used, disk_total, disk_used = _get_ram_and_disk()
    info = None
    if shutil.which("nvidia-smi"):
        info = _probe_nvidia()
    if info is None and shutil.which("rocm-smi"):
        info = _probe_rocm()
    if info is None:
        info = _probe_drm()
    if info is None:
        info = _probe_cpu()

    info.ram_total_mb = ram_total
    info.ram_used_mb = ram_used
    info.disk_total_mb = disk_total
    info.disk_used_mb = disk_used
    return info


def _probe_drm() -> GpuInfo | None:
    """Lit la VRAM via sysfs DRM (GPU discret AMD avec pilote amdgpu, sans rocm-smi).
    Exclut les iGPU/APU dont la VRAM est partagée avec la RAM système."""
    import glob
    try:
        for card_path in sorted(glob.glob("/sys/class/drm/card*/device")):
            vram_total_path = Path(card_path) / "mem_info_vram_total"
            vram_used_path = Path(card_path) / "mem_info_vram_used"
            if not vram_total_path.exists():
                continue
            total_b = int(vram_total_path.read_text().strip())
            if total_b == 0:
                continue
            # Ignore les iGPU/APU (VRAM UMA < 4 GiB) — leur VRAM est de la RAM système
            # réservée, pas de la mémoire graphique dédiée. Le build CPU de llama-server
            # ne peut pas utiliser un iGPU (pas de backend ROCm/Vulkan).
            if total_b < 4 * 1024 ** 3:
                continue
            # Essaie de lire le nom du GPU depuis sysfs
            gpu_name: str | None = None
            for name_file in ("product_name", "label"):
                name_path = Path(card_path) / name_file
                try:
                    val = name_path.read_text().strip()
                    if val:
                        gpu_name = val
                        break
                except Exception:
                    pass
            if not gpu_name:
                gpu_name = "AMD GPU"
            used_b = int(vram_used_path.read_text().strip()) if vram_used_path.exists() else 0
            return GpuInfo(
                model=gpu_name,
                vram_total_mb=total_b // (1024 * 1024),
                vram_used_mb=used_b // (1024 * 1024),
                ram_total_mb=None, ram_used_mb=None, disk_total_mb=None, disk_used_mb=None,
            )
    except Exception:
        pass
    return None


def _cpu_model_name() -> str:
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "CPU"


def _probe_cpu() -> GpuInfo:
    return GpuInfo(
        model=_cpu_model_name(),
        vram_total_mb=None,
        vram_used_mb=None,
        ram_total_mb=None,
        ram_used_mb=None,
        disk_total_mb=None,
        disk_used_mb=None,
    )


def _probe_nvidia() -> GpuInfo | None:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    line = out.strip().splitlines()[0] if out.strip() else None
    if not line:
        return None
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 3:
        return None
    try:
        return GpuInfo(model=parts[0], vram_total_mb=int(parts[1]), vram_used_mb=int(parts[2]), ram_total_mb=None, ram_used_mb=None, disk_total_mb=None, disk_used_mb=None)
    except ValueError:
        return None


def _probe_rocm() -> GpuInfo | None:
    try:
        out = subprocess.check_output(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--csv"],
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    # parsing best-effort, ROCm csv variations selon les versions
    model: str | None = None
    total_b: int | None = None
    used_b: int | None = None
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
        if "vram used" in low:
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip().isdigit():
                used_b = int(parts[1].strip())
    return GpuInfo(
        model=model,
        vram_total_mb=total_b // (1024 * 1024) if total_b else None,
        vram_used_mb=used_b // (1024 * 1024) if used_b else None,
        ram_total_mb=None,
        ram_used_mb=None,
        disk_total_mb=None,
        disk_used_mb=None,
    )
