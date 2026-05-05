from __future__ import annotations

import shutil
from dataclasses import dataclass

@dataclass
class RamInfo:
    ram_total_mb: int | None
    ram_used_mb: int | None

@dataclass
class DiskInfo:
    disk_total_mb: int | None
    disk_used_mb: int | None

def probe_ram() -> RamInfo:
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

        return RamInfo(ram_total_mb=total_kb // 1024, ram_used_mb=used_kb // 1024)
    except Exception:
        return RamInfo(ram_total_mb=None, ram_used_mb=None)

def probe_disk() -> DiskInfo:
    try:
        usage = shutil.disk_usage("/")
        return DiskInfo(
            disk_total_mb=usage.total // (1024 * 1024),
            disk_used_mb=usage.used // (1024 * 1024)
        )
    except Exception:
        return DiskInfo(disk_total_mb=None, disk_used_mb=None)
