"""Tests unitaires du router (sélection node)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from spouet.db.models import Model, Node
from spouet.nodes.router import NoSuitableNodeError, pick_node


def _node(name: str, vram_used: int | None, last_seen_offset: int = 0) -> Node:
    n = Node(
        name=name,
        host=f"{name}.lan",
        port=11434,
        status="online",
        last_seen=datetime.now(timezone.utc) - timedelta(seconds=last_seen_offset),
        vram_used_mb=vram_used,
        vram_total_mb=24000,
    )
    n.id = uuid4()
    return n


def _model(node_id, name="llama3.1:8b", supports_tools=True):
    m = Model(node_id=node_id, name=name, supports_tools=supports_tools, last_seen=datetime.now(timezone.utc))
    m.id = uuid4()
    return m


def _mock_db(rows: list[tuple[Node, Model]]):
    db = AsyncMock()
    result = AsyncMock()
    result.all = lambda: rows
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_pick_least_loaded() -> None:
    n1 = _node("alpha", vram_used=8000)
    n2 = _node("beta", vram_used=2000)
    db = _mock_db([(n1, _model(n1.id)), (n2, _model(n2.id))])
    choice = await pick_node(db, "llama3.1:8b")
    assert choice.name == "beta"  # moins de VRAM utilisée


@pytest.mark.asyncio
async def test_pick_excludes_failed_nodes() -> None:
    n1 = _node("alpha", vram_used=2000)
    n2 = _node("beta", vram_used=8000)
    db = _mock_db([(n1, _model(n1.id)), (n2, _model(n2.id))])
    choice = await pick_node(db, "llama3.1:8b", exclude_node_ids={n1.id})
    assert choice.name == "beta"


@pytest.mark.asyncio
async def test_no_node_raises() -> None:
    db = _mock_db([])
    with pytest.raises(NoSuitableNodeError):
        await pick_node(db, "llama3.1:8b")


@pytest.mark.asyncio
async def test_unknown_vram_penalized() -> None:
    n1 = _node("alpha", vram_used=None)  # VRAM inconnue → 1024 par défaut
    n2 = _node("beta", vram_used=500)
    db = _mock_db([(n1, _model(n1.id)), (n2, _model(n2.id))])
    choice = await pick_node(db, "llama3.1:8b")
    assert choice.name == "beta"
