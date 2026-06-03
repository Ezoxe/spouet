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
from spouet.core.logging import get_logger
from spouet.db.models import Model, Node

logger = get_logger(__name__)


class NoSuitableNodeError(RuntimeError):
    """Aucun node disponible pour ce modèle."""


@dataclass
class NodeChoice:
    node_id: UUID
    name: str
    base_url: str
    model: str
    supports_tools: bool
    host: str
    port: int
    agent_port: int | None
    needs_load: bool
    # Taille de contexte llama.cpp du node (None si inconnue / pas encore chargé).
    # Permet à l'orchestrator de dimensionner la troncature d'historique sur le
    # vrai n_ctx du modèle plutôt qu'un budget fixe.
    n_ctx: int | None = None


async def pick_node(
    db: AsyncSession,
    model: str,
    *,
    exclude_node_ids: set[UUID] | None = None,
) -> NodeChoice:
    """Choisit le meilleur node pour `model`.

    Stratégie de tri (par ordre de priorité) :
      1. Nodes où le modèle est déjà chargé (`llama_running` & `llama_model_loaded == model`)
      2. VRAM utilisée croissante (least-loaded)
      3. Nom alphabétique (stabilité)

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
        # Diagnostic : remonter ce qui est réellement disponible pour aider à
        # identifier les divergences (modèle absent, node offline, nom mal
        # normalisé côté agent…).
        diag_rows = (
            await db.execute(
                select(Node, Model)
                .join(Model, Model.node_id == Node.id)
                .where(Node.last_seen.is_not(None), Node.last_seen >= threshold)
            )
        ).all()
        seen: dict[str, list[str]] = {}
        for n, m in diag_rows:
            seen.setdefault(n.name, []).append(m.name)
        logger.warning(
            "router.no_suitable_node",
            requested_model=model,
            requested_repr=repr(model),
            online_nodes=list(seen.keys()),
            online_models={k: v for k, v in seen.items()},
            excluded=[str(x) for x in exclude],
        )
        if not seen:
            detail = "no node is online (heartbeat stale or absent)"
        else:
            avail = "; ".join(f"{n}=[{', '.join(sorted(ms))}]" for n, ms in seen.items())
            detail = f"online nodes report: {avail}"
        raise NoSuitableNodeError(
            f"No online node has model '{model}'. {detail}"
        )

    def is_loaded(node: Node, mdl: Model) -> bool:
        return bool(node.llama_running) and node.llama_model_loaded == mdl.name

    def sort_key(item: tuple[Node, Model]) -> tuple[int, int, str]:
        node, mdl = item
        # Priorité 1 (0=hot, 1=cold) : préfère un node où le modèle est déjà chargé
        hot = 0 if is_loaded(node, mdl) else 1
        # VRAM "used" inconnue → on pénalise (1 GB virtuel)
        vram_used = node.vram_used_mb if node.vram_used_mb is not None else 1024
        return (hot, vram_used, node.name)

    node, mdl = min(candidates, key=sort_key)
    return NodeChoice(
        node_id=node.id,
        name=node.name,
        base_url=f"http://{node.host}:{node.port}",
        model=mdl.name,
        supports_tools=mdl.supports_tools,
        host=node.host,
        port=node.port,
        agent_port=node.agent_port,
        needs_load=not is_loaded(node, mdl),
        # Pertinent surtout pour un node « hot » (modèle déjà chargé) : la valeur
        # reflète alors exactement le n_ctx en cours. Pour un cold-start elle peut
        # être absente / dater du modèle précédent → build_messages retombe sur
        # son défaut prudent.
        n_ctx=node.llama_n_ctx if is_loaded(node, mdl) else None,
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
