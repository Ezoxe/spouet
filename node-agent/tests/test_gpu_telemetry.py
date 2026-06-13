"""Tests de la télémétrie GPU (gpu_telemetry).

- Parsing du CSV nvidia-smi, y compris les sentinelles `[N/A]` (cartes datacenter
  sans ventilo / sans power.limit exposé).
- Lecture sysfs AMD via un arbre /sys factice (tmp_path).
"""

from __future__ import annotations

from spouet_agent import gpu_telemetry as gt


def test_parse_nvidia_csv_two_gpus_with_na():
    csv = (
        "0, NVIDIA GeForce RTX 4090, 45, 12, 1024, 24576, 63, 215.5, 450.0, 2520, 10501, 38\n"
        "1, NVIDIA A100-SXM4-40GB, 99, 50, 40000, 40960, 71, 250.0, [N/A], 1410, 1215, [N/A]\n"
    )
    out = gt._parse_nvidia_csv(csv)
    assert len(out) == 2

    a = out[0]
    assert a.index == 0
    assert a.name == "NVIDIA GeForce RTX 4090"
    assert a.util_pct == 45.0
    assert a.mem_util_pct == 12.0
    assert a.vram_used_mb == 1024
    assert a.vram_total_mb == 24576
    assert a.temp_c == 63.0
    assert a.power_w == 215.5
    assert a.power_limit_w == 450.0
    assert a.clock_sm_mhz == 2520
    assert a.clock_mem_mhz == 10501
    assert a.fan_pct == 38.0

    b = out[1]
    assert b.index == 1
    assert b.vram_total_mb == 40960
    # Capteurs absents → None (et non 0)
    assert b.power_limit_w is None
    assert b.fan_pct is None


def test_parse_nvidia_csv_ignores_garbage_lines():
    csv = "\nthis is not csv\n0, GPU, 10, 5, 100, 200, 50, 30, 60, 1000, 2000, 25\n"
    out = gt._parse_nvidia_csv(csv)
    assert len(out) == 1
    assert out[0].util_pct == 10.0


def _make_amd_card(root, *, name="AMD Radeon RX 7900 XTX"):
    dev = root / "card0" / "device"
    dev.mkdir(parents=True)
    (dev / "uevent").write_text("DRIVER=amdgpu\nPCI_ID=1002:744C\n")
    (dev / "product_name").write_text(name + "\n")
    (dev / "gpu_busy_percent").write_text("77\n")
    (dev / "mem_info_vram_used").write_text(str(8 * 1024**3) + "\n")
    (dev / "mem_info_vram_total").write_text(str(16 * 1024**3) + "\n")
    (dev / "pp_dpm_sclk").write_text("0: 500Mhz\n1: 2100Mhz *\n2: 2400Mhz\n")
    (dev / "pp_dpm_mclk").write_text("0: 96Mhz\n1: 1249Mhz *\n")
    hw = dev / "hwmon" / "hwmon0"
    hw.mkdir(parents=True)
    (hw / "temp1_input").write_text("65000\n")        # m°C → 65.0
    (hw / "power1_average").write_text("120000000\n")  # µW → 120.0 W
    (hw / "power1_cap").write_text("355000000\n")      # µW → 355.0 W
    (hw / "pwm1").write_text("128\n")                  # /255 → ~50.2 %
    return root


def test_probe_amd_sysfs(tmp_path, monkeypatch):
    # _probe_amd court-circuite hors Linux : on simule Linux pour le test.
    monkeypatch.setattr(gt.platform, "system", lambda: "Linux")
    _make_amd_card(tmp_path)

    out = gt._probe_amd(drm_root=str(tmp_path))
    assert len(out) == 1
    g = out[0]
    assert g.name == "AMD Radeon RX 7900 XTX"
    assert g.util_pct == 77.0
    assert g.vram_used_mb == 8192
    assert g.vram_total_mb == 16384
    assert g.mem_util_pct == 50.0
    assert g.temp_c == 65.0
    assert g.power_w == 120.0
    assert g.power_limit_w == 355.0
    assert g.clock_sm_mhz == 2100
    assert g.clock_mem_mhz == 1249
    assert g.fan_pct == 50.2


def test_probe_amd_skips_non_amdgpu(tmp_path, monkeypatch):
    monkeypatch.setattr(gt.platform, "system", lambda: "Linux")
    dev = tmp_path / "card0" / "device"
    dev.mkdir(parents=True)
    (dev / "uevent").write_text("DRIVER=i915\n")  # iGPU Intel → ignoré
    assert gt._probe_amd(drm_root=str(tmp_path)) == []


def test_probe_telemetry_cpu_returns_empty():
    assert gt.probe_gpu_telemetry("cpu") == []
