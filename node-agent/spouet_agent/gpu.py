"""Détection GPU et VRAM (NVIDIA et AMD)."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class GpuInfo:
    model: str | None
    vram_total_mb: int | None
    vram_used_mb: int | None


def probe_gpu() -> GpuInfo:
    """Tente nvidia-smi puis rocm-smi. Retourne None partout si rien trouvé."""
    if shutil.which("nvidia-smi"):
        info = _probe_nvidia()
        if info is not None:
            return info
    if shutil.which("rocm-smi"):
        info = _probe_rocm()
        if info is not None:
            return info
    return GpuInfo(model=None, vram_total_mb=None, vram_used_mb=None)


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
        return GpuInfo(model=parts[0], vram_total_mb=int(parts[1]), vram_used_mb=int(parts[2]))
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
    )
