"""Tests du loader/validator de manifest de tool."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from spouet.tools.manifest import ManifestError, load_manifest, validate_args

_BASE = {
    "slug": "demo",
    "name": "Demo",
    "version": "0.1.0",
    "image": "spouet/tool-demo:0.1.0",
    "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}},
}


def _write(tmp_path: Path, extra: dict) -> Path:
    data = {**_BASE, **extra}
    p = tmp_path / "manifest.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_network_none_no_approval(tmp_path: Path) -> None:
    m = load_manifest(_write(tmp_path, {"network": "none"}))
    assert m.network == "none"
    assert m.requires_approval is False


def test_network_internal_accepted_and_requires_approval(tmp_path: Path) -> None:
    m = load_manifest(_write(tmp_path, {"network": "internal"}))
    assert m.network == "internal"
    assert m.requires_approval is True


def test_network_bridge_requires_approval(tmp_path: Path) -> None:
    m = load_manifest(_write(tmp_path, {"network": "bridge"}))
    assert m.requires_approval is True


def test_invalid_network_rejected(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, {"network": "host"}))


def test_validate_args_reports_errors() -> None:
    schema = {
        "type": "object",
        "required": ["x"],
        "properties": {"x": {"type": "integer"}},
    }
    assert validate_args(schema, {"x": 3}) == []
    errs = validate_args(schema, {})
    assert errs  # le champ requis manquant doit produire une erreur
    assert any("x" in e.lower() or "required" in e.lower() for e in errs)
