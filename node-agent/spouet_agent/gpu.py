"""Détection GPU et VRAM (NVIDIA et AMD)."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class GpuInfo:
    model: str | None
    vram_total_mb: int | None
    vram_used_mb: int | None
    ram_total_mb: int | None
    ram_used_mb: int | None
    disk_total_mb: int | None
    disk_used_mb: int | None


def _get_ram_and_disk() -> tuple[int|None, int|None, int|None, int|None]:
    import shutil
    try:
        with open("/proc/meminfo", "r") as f:
            meminfo = f.read()
        total_kb = 0
        available_kb = 0
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                total_kb = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                available_kb = int(line.split()[1])

        ram_total_mb = total_kb // 1024 if total_kb > 0 else None
        ram_used_mb = (total_kb - available_kb) // 1024 if total_kb > 0 and available_kb > 0 else None
    except Exception:
        ram_total_mb, ram_used_mb = None, None

    try:
        usage = shutil.disk_usage("/")
        disk_total_mb = usage.total // (1024 * 1024)
        disk_used_mb = usage.used // (1024 * 1024)
    except Exception:
        disk_total_mb, disk_used_mb = None, None

    return ram_total_mb, ram_used_mb, disk_total_mb, disk_used_mb

def probe_gpu() -> GpuInfo:
    """Tente nvidia-smi puis rocm-smi. Retourne le CPU et la RAM système si rien trouvé."""
    ram_total, ram_used, disk_total, disk_used = _get_ram_and_disk()
    info = None
    if shutil.which("nvidia-smi"):
        info = _probe_nvidia()
    if info is None and shutil.which("rocm-smi"):
        info = _probe_rocm()
    if info is None:
        info = _probe_cpu()

    info.ram_total_mb = ram_total
    info.ram_used_mb = ram_used
    info.disk_total_mb = disk_total
    info.disk_used_mb = disk_used
    return info


def _probe_cpu() -> GpuInfo:
    try:
        with open("/proc/meminfo", "r") as f:
            meminfo = f.read()
        total_kb = 0
        available_kb = 0
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                total_kb = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                available_kb = int(line.split()[1])

        if total_kb > 0 and available_kb > 0:
            used_kb = total_kb - available_kb
        else:
            used_kb = 0

        vram_total_mb = total_kb // 1024
        vram_used_mb = used_kb // 1024

        model = "CPU"
        try:
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if line.startswith("model name"):
                        model = line.split(":", 1)[1].strip()
                        break
        except FileNotFoundError:
            model = platform.processor() or "CPU"

        return GpuInfo(model=model, vram_total_mb=vram_total_mb, vram_used_mb=vram_used_mb, ram_total_mb=None, ram_used_mb=None, disk_total_mb=None, disk_used_mb=None)
    except Exception:
        return GpuInfo(model=None, vram_total_mb=None, vram_used_mb=None, ram_total_mb=None, ram_used_mb=None, disk_total_mb=None, disk_used_mb=None)


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
