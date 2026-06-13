"""Télémétrie GPU live (température, usage, puissance, ventilo, fréquences).

Complète `capabilities.py` (détection statique au boot) par des **mesures
instantanées** rafraîchies à chaque heartbeat. Multi-GPU : une entrée par carte.

Best-effort par conception : toute erreur (binaire absent, format inattendu,
permissions) retombe sur une liste vide ou des champs `None` — jamais
d'exception qui ferait échouer le heartbeat.

Sources :
  - NVIDIA : un seul appel `nvidia-smi --query-gpu=…` (toutes les cartes).
  - AMD    : sysfs `/sys/class/drm/card*/device` (amdgpu) + hwmon.
"""

from __future__ import annotations

import glob
import platform
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

# Ordre EXACT des champs demandés à nvidia-smi (cf. _NVIDIA_QUERY).
_NVIDIA_QUERY = (
    "index,name,utilization.gpu,utilization.memory,memory.used,memory.total,"
    "temperature.gpu,power.draw,enforced.power.limit,clocks.sm,clocks.mem,fan.speed"
)


@dataclass
class GpuTelemetry:
    """Mesures instantanées d'une carte GPU."""

    index: int
    name: str | None = None
    util_pct: float | None = None          # charge GPU (cœurs) %
    mem_util_pct: float | None = None       # charge contrôleur mémoire %
    vram_used_mb: int | None = None
    vram_total_mb: int | None = None
    temp_c: float | None = None
    power_w: float | None = None
    power_limit_w: float | None = None
    fan_pct: float | None = None
    clock_sm_mhz: int | None = None
    clock_mem_mhz: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Entrée publique
# ---------------------------------------------------------------------------


def probe_gpu_telemetry(compute_class: str) -> list[GpuTelemetry]:
    """Retourne la télémétrie de chaque GPU, ou `[]` si non applicable/échec.

    `compute_class` provient des capabilities (source de vérité). On ne sonde
    que le bon backend pour éviter des appels inutiles (et lents).
    """
    if compute_class == "cuda":
        return _probe_nvidia()
    if compute_class == "rocm":
        return _probe_amd()
    return []


# ---------------------------------------------------------------------------
# NVIDIA
# ---------------------------------------------------------------------------


def _probe_nvidia() -> list[GpuTelemetry]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", f"--query-gpu={_NVIDIA_QUERY}", "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return _parse_nvidia_csv(out)


def _parse_nvidia_csv(text: str) -> list[GpuTelemetry]:
    """Parse la sortie CSV de nvidia-smi (testable sans le binaire)."""
    result: list[GpuTelemetry] = []
    for line in text.strip().splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 12:
            continue
        idx = _as_int(parts[0])
        result.append(
            GpuTelemetry(
                index=idx if idx is not None else len(result),
                name=parts[1] or None,
                util_pct=_as_float(parts[2]),
                mem_util_pct=_as_float(parts[3]),
                vram_used_mb=_as_int(parts[4]),
                vram_total_mb=_as_int(parts[5]),
                temp_c=_as_float(parts[6]),
                power_w=_as_float(parts[7]),
                power_limit_w=_as_float(parts[8]),
                clock_sm_mhz=_as_int(parts[9]),
                clock_mem_mhz=_as_int(parts[10]),
                fan_pct=_as_float(parts[11]),
            )
        )
    return result


def _as_float(v: str | None) -> float | None:
    """Convertit une valeur nvidia-smi/sysfs en float, en filtrant les sentinelles.

    nvidia-smi renvoie `[N/A]`, `[Not Supported]`, `[Insufficient Permissions]`
    pour les capteurs absents (ventilo des cartes datacenter, p.ex.).
    """
    if v is None:
        return None
    s = v.strip()
    if not s or s.startswith("["):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _as_int(v: str | None) -> int | None:
    f = _as_float(v)
    return int(f) if f is not None else None


# ---------------------------------------------------------------------------
# AMD (sysfs + hwmon)
# ---------------------------------------------------------------------------


def _probe_amd(drm_root: str = "/sys/class/drm") -> list[GpuTelemetry]:
    if platform.system() != "Linux":
        return []
    try:
        candidates = sorted(glob.glob(f"{drm_root}/card*/device"))
    except OSError:
        return []

    result: list[GpuTelemetry] = []
    for card_path in candidates:
        card = Path(card_path)
        if _drm_driver(card) != "amdgpu":
            continue
        tele = _amd_card_telemetry(card, index=len(result))
        if tele is not None:
            result.append(tele)
    return result


def _drm_driver(card: Path) -> str:
    try:
        for line in (card / "uevent").read_text().splitlines():
            if line.startswith("DRIVER="):
                return line.split("=", 1)[1].strip().lower()
    except OSError:
        pass
    return ""


def _amd_card_telemetry(card: Path, index: int) -> GpuTelemetry | None:
    name = _read_str(card, ("product_name", "marketing_name", "device_name", "label"))
    util = _read_int(card / "gpu_busy_percent")
    used_b = _read_int(card / "mem_info_vram_used")
    total_b = _read_int(card / "mem_info_vram_total")
    used_mb = used_b // (1024 * 1024) if used_b is not None else None
    total_mb = total_b // (1024 * 1024) if total_b is not None else None
    mem_util = (
        round(100.0 * used_b / total_b, 1)
        if used_b is not None and total_b
        else None
    )

    hwmon = _amd_hwmon_dir(card)
    temp_c = power_w = power_limit_w = fan_pct = None
    if hwmon is not None:
        temp_raw = _read_int(hwmon / "temp1_input")  # milli-°C
        temp_c = round(temp_raw / 1000.0, 1) if temp_raw is not None else None
        power_raw = _read_int(hwmon / "power1_average")
        if power_raw is None:
            power_raw = _read_int(hwmon / "power1_input")
        power_w = round(power_raw / 1_000_000.0, 1) if power_raw is not None else None
        cap_raw = _read_int(hwmon / "power1_cap")
        power_limit_w = round(cap_raw / 1_000_000.0, 1) if cap_raw is not None else None
        pwm = _read_int(hwmon / "pwm1")  # 0-255
        fan_pct = round(100.0 * pwm / 255.0, 1) if pwm is not None else None

    clock_sm = _amd_active_clock(card / "pp_dpm_sclk")
    clock_mem = _amd_active_clock(card / "pp_dpm_mclk")

    # Si rien d'exploitable, on n'ajoute pas une carte vide.
    if all(
        v is None
        for v in (name, util, used_mb, total_mb, temp_c, power_w, clock_sm)
    ):
        return None

    return GpuTelemetry(
        index=index,
        name=name,
        util_pct=float(util) if util is not None else None,
        mem_util_pct=mem_util,
        vram_used_mb=used_mb,
        vram_total_mb=total_mb,
        temp_c=temp_c,
        power_w=power_w,
        power_limit_w=power_limit_w,
        fan_pct=fan_pct,
        clock_sm_mhz=clock_sm,
        clock_mem_mhz=clock_mem,
    )


def _amd_hwmon_dir(card: Path) -> Path | None:
    try:
        for d in sorted((card / "hwmon").glob("hwmon*")):
            if d.is_dir():
                return d
    except OSError:
        pass
    return None


def _amd_active_clock(path: Path) -> int | None:
    """Lit la fréquence active (ligne marquée `*`) d'un fichier pp_dpm_*clk.

    Format : `0: 500Mhz\n1: 1200Mhz *\n…` → retourne 1200.
    """
    try:
        for line in path.read_text().splitlines():
            if "*" in line:
                # ex. "1: 1200Mhz *"
                token = line.split(":", 1)[1].strip().split()[0]
                digits = "".join(c for c in token if c.isdigit())
                return int(digits) if digits else None
    except (OSError, IndexError, ValueError):
        pass
    return None


def _read_str(base: Path, names: tuple[str, ...]) -> str | None:
    for n in names:
        try:
            val = (base / n).read_text().strip()
            if val:
                return val
        except OSError:
            continue
    return None


def _read_int(p: Path) -> int | None:
    try:
        return int(p.read_text().strip())
    except (OSError, ValueError):
        return None
