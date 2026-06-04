"""Tests des helpers purs des built-in tools (validation, slug, URLs, matching)."""

from __future__ import annotations

from spouet.orchestrator import builtin_tools as bt


def test_is_builtin():
    assert bt.is_builtin("web_search")
    assert bt.is_builtin("run_macro")
    assert not bt.is_builtin("spotify")
    assert not bt.is_builtin(None)


def test_tool_defs_capability_aware():
    names_off = {d["function"]["name"] for d in bt.tool_defs(desktop_connected=False)}
    names_on = {d["function"]["name"] for d in bt.tool_defs(desktop_connected=True)}
    # web_search / show_visual / list_macros toujours présents
    assert {"web_search", "show_visual", "list_macros"} <= names_off
    # pilotage PC seulement si client connecté
    assert "run_macro" not in names_off
    assert {"run_macro", "define_macro", "run_desktop_action"} <= names_on


def test_tool_defs_generate_image_gated():
    # generate_image n'apparaît que si le moteur d'images est activé.
    off = {d["function"]["name"] for d in bt.tool_defs(desktop_connected=False)}
    on = {
        d["function"]["name"]
        for d in bt.tool_defs(desktop_connected=False, images_enabled=True)
    }
    assert "generate_image" not in off
    assert "generate_image" in on


def test_opt_int():
    assert bt._opt_int(None) is None
    assert bt._opt_int("512") == 512
    assert bt._opt_int(768) == 768
    assert bt._opt_int("pas un nombre") is None


def test_validate_step_launch_app():
    step, errs = bt._validate_step({"action": "launch_app", "app": "CurseForge", "monitor": 1})
    assert not errs
    assert step == {"action": "launch_app", "app": "CurseForge", "monitor": 1}


def test_validate_step_open_url_normalizes_scheme():
    step, errs = bt._validate_step({"action": "open_url", "url": "youtube.com", "monitor": 2})
    assert not errs
    assert step["url"] == "https://youtube.com"
    assert step["monitor"] == 2


def test_validate_step_rejects_unknown_action():
    _, errs = bt._validate_step({"action": "format_c_drive"})
    assert errs


def test_validate_step_requires_app_or_url():
    _, errs = bt._validate_step({"action": "launch_app"})
    assert errs
    _, errs2 = bt._validate_step({"action": "open_url", "url": "pas une url"})
    assert errs2


def test_validate_step_bad_monitor_and_mode():
    _, errs = bt._validate_step({"action": "launch_app", "app": "X", "monitor": "deux"})
    assert any("monitor" in e for e in errs)
    _, errs2 = bt._validate_step({"action": "launch_app", "app": "X", "mode": "tiny"})
    assert any("mode" in e for e in errs2)


def test_slugify_accents():
    assert bt._slugify("soirée Minecraft") == "soiree-minecraft"
    assert bt._slugify("  Café  du   matin ") == "cafe-du-matin"


def test_safe_url():
    assert bt._safe_url("https://x.com") == "https://x.com"
    assert bt._safe_url("youtube.com") == "https://youtube.com"
    assert bt._safe_url("ftp://x") is None
    assert bt._safe_url("") is None
    assert bt._safe_url("juste du texte") is None


def test_app_matches_fuzzy_and_accents():
    known = ["CurseForge", "Steam", "Visual Studio Code"]
    assert bt._app_matches("curseforge", known)
    assert bt._app_matches("vs code", known) is False  # pas de sous-chaîne commune
    assert bt._app_matches("Visual Studio Code", known)
    assert bt._app_matches("notepad", known) is False


def test_clamp_duration():
    assert bt._clamp_duration(None) == 7000
    assert bt._clamp_duration(500) == 1000
    assert bt._clamp_duration(999999) == 30000
    assert bt._clamp_duration(5000) == 5000
