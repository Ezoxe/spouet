"""Détection GPU/CPU + métriques RAM/disque.

Façade qui utilise `capabilities.probe_capabilities()` comme source de vérité
pour la classification GPU vs CPU, et complète avec les métriques système
RAM/disque (utilisées par le heartbeat et l'API de contrôle).
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass

from spouet_agent.capabilities import NodeCapabilities, probe_capabilities


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


def _probe_vram_used(compute_class: str) -> int | None:
    """Lit la VRAM utilisée pour un GPU dédié. Best-effort, retourne None sinon."""
    if compute_class == "cuda":
        try:
            import subprocess

            out = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=5,
            )
            line = out.strip().splitlines()[0] if out.strip() else None
            if line:
                return int(line.strip())
        except Exception:
            return None
    # ROCm / DRM : pas de lecture stable cross-version, on laisse None.
    return None


def probe_gpu() -> GpuInfo:
    """Retourne `GpuInfo` populé (model/vram via capabilities, RAM/disk via /proc).

    Utilisé par le heartbeat et l'API de contrôle. Pour les besoins riches
    (compute_class, gpu_kind, llama_variant, warnings…), utiliser directement
    `probe_capabilities()`.
    """
    caps = probe_capabilities()
    return _gpu_info_from_caps(caps)


def gpu_info_from_capabilities(caps: NodeCapabilities) -> GpuInfo:
    """Pour les appelants qui ont déjà un `NodeCapabilities` en main."""
    return _gpu_info_from_caps(caps)


def _gpu_info_from_caps(caps: NodeCapabilities) -> GpuInfo:
    ram_total, ram_used, disk_total, disk_used = _get_ram_and_disk()
    # Pour les iGPU classés CPU on n'expose pas de VRAM (sinon l'UI laisse penser
    # qu'on dispose d'un vrai GPU).
    if caps.compute_class == "cpu":
        model = caps.cpu_model or "CPU"
        vram_total: int | None = None
        vram_used: int | None = None
    else:
        model = caps.gpu_model
        vram_total = caps.vram_total_mb
        vram_used = _probe_vram_used(caps.compute_class)

    return GpuInfo(
        model=model,
        vram_total_mb=vram_total,
        vram_used_mb=vram_used,
        ram_total_mb=ram_total,
        ram_used_mb=ram_used,
        disk_total_mb=disk_total,
        disk_used_mb=disk_used,
    )
