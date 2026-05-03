"""Sélection d'un node Ollama pour un modèle donné.

Stratégie : parmi les nodes ONLINE qui ont le modèle :
  1. exclure ceux dont la VRAM résiduelle ne suffit pas (si on a la taille du modèle)
  2. trier par VRAM utilisée croissante (least-loaded)
  3. en cas d'égalité, ordre alphabétique du nom (stabilité)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.config import settings
from spouet.db.models import Model, Node


class NoSuitableNodeError(RuntimeError):
    """Aucun node disponible pour ce modèle."""


@dataclass
class NodeChoice:
    node_id: UUID
    name: str
    base_url: str
    model: str
    supports_tools: bool


async def pick_node(
    db: AsyncSession,
    model: str,
    *,
    exclude_node_ids: set[UUID] | None = None,
) -> NodeChoice:
    """Choisit le meilleur node pour `model`.

    Lève NoSuitableNodeError si aucun candidat.
    `exclude_node_ids` : à utiliser pour le failover après crash.
    """
    exclude = exclude_node_ids or set()
    threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.node_offline_after_s)

    rows = (
        await db.execute(
            select(Node, Model)
            .join(Model, Model.node_id == Node.id)
            .where(
                Model.name == model,
                Node.last_seen.is_not(None),
                Node.last_seen >= threshold,
            )
        )
    ).all()

    candidates: list[tuple[Node, Model]] = [
        (n, m) for (n, m) in rows if n.id not in exclude
    ]
    if not candidates:
        raise NoSuitableNodeError(f"No online node has model '{model}'")

    def sort_key(item: tuple[Node, Model]) -> tuple[int, str]:
        node, _ = item
        # VRAM "used" inconnue → on pénalise (1 GB virtuel)
        vram_used = node.vram_used_mb if node.vram_used_mb is not None else 1024
        return (vram_used, node.name)

    node, mdl = min(candidates, key=sort_key)
    return NodeChoice(
        node_id=node.id,
        name=node.name,
        base_url=f"http://{node.host}:{node.port}",
        model=mdl.name,
        supports_tools=mdl.supports_tools,
    )


async def list_available_models(db: AsyncSession) -> list[dict[str, object]]:
    """Liste agrégée : un modèle peut être présent sur plusieurs nodes."""
    threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.node_offline_after_s)
    rows = (
        await db.execute(
            select(Node, Model)
            .join(Model, Model.node_id == Node.id)
            .where(Node.last_seen.is_not(None), Node.last_seen >= threshold)
        )
    ).all()
    by_name: dict[str, dict[str, object]] = {}
    for n, m in rows:
        entry = by_name.setdefault(
            m.name,
            {
                "name": m.name,
                "supports_tools": m.supports_tools,
                "size_bytes": m.size_bytes,
                "nodes": [],
            },
        )
        entry["nodes"].append({"id": str(n.id), "name": n.name})  # type: ignore[union-attr]
    return sorted(by_name.values(), key=lambda x: x["name"])  # type: ignore[arg-type,return-value]
