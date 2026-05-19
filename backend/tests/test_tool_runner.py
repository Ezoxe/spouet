"""Tests du runner de tools — résolution du mode réseau (fonction pure)."""

from __future__ import annotations

from spouet.core.config import settings
from spouet.tools.runner import _resolve_network


def test_resolve_network_none_passthrough() -> None:
    assert _resolve_network("none") == "none"


def test_resolve_network_bridge_passthrough() -> None:
    assert _resolve_network("bridge") == "bridge"


def test_resolve_network_internal_maps_to_spouet_network() -> None:
    # internal est un alias logique vers le réseau docker-compose Spouet.
    assert _resolve_network("internal") == settings.tool_docker_network
