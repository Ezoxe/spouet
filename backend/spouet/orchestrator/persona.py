"""Personnalité « Spouet ».

Construit un system prompt qui donne à l'IA conscience d'elle-même : son nom,
le node sur lequel elle s'exécute, le modèle Ollama actif, ses ressources et
les capacités de la plateforme. Injecté au premier tour via build_extra_system.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.config import settings
from spouet.db.models import Model, Node, Tool

PERSONA_NAME = "Spouet"

BASE_PERSONA = (
    "Tu es Spouet, une IA self-hosted exécutée sur une plateforme d'orchestration "
    "multi-nodes Ollama du même nom. Tu n'es pas un assistant cloud anonyme : tu "
    "tournes en local, sur le matériel de l'utilisateur, sans télémétrie. "
    "Réponds toujours en français par défaut, sauf si l'utilisateur s'exprime "
    "dans une autre langue. Sois direct, précis, et concis. "
    "Quand tu ne sais pas, dis-le clairement plutôt que d'inventer. "
    "Tu peux exécuter des outils sandbox (Docker), accéder à une mémoire "
    "long-terme et à des documents indexés (RAG) lorsque c'est pertinent."
)


async def build_persona_prompt(
    db: AsyncSession,
    *,
    node_name: str | None = None,
    model_name: str | None = None,
) -> str:
    """Construit le system prompt complet en prenant en compte l'état du cluster.

    `node_name` / `model_name` : si fournis, le prompt mentionne explicitement
    où la requête s'exécute (à passer après pick_node). Sinon, on liste l'état
    global du cluster.
    """
    parts: list[str] = [BASE_PERSONA]

    cluster = await _cluster_summary(db)
    if cluster:
        parts.append(cluster)

    if node_name and model_name:
        parts.append(
            f"Pour cette réponse, tu tournes sur le node « {node_name} » avec le "
            f"modèle Ollama « {model_name} »."
        )

    parts.append(
        "Capacités exposées par la plateforme : conversations multi-tours, "
        "appels de tools sandboxés (HITL pour les outils sensibles), tâches "
        "planifiées (Celery), mémoire persistante par utilisateur, RAG "
        "PGVector (modèle d'embedding nomic-embed-text), connecteurs externes."
    )

    return "\n\n".join(parts)


async def _cluster_summary(db: AsyncSession) -> str | None:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.node_offline_after_s)

    nodes = (
        await db.execute(
            select(Node).where(Node.last_seen.is_not(None), Node.last_seen >= threshold)
        )
    ).scalars().all()

    total_models = (
        await db.execute(select(func.count(func.distinct(Model.name))))
    ).scalar_one() or 0

    enabled_tools = (
        await db.execute(select(func.count()).select_from(Tool).where(Tool.enabled.is_(True)))
    ).scalar_one() or 0

    if not nodes:
        return (
            "État actuel du cluster : aucun node Ollama en ligne. Si l'utilisateur "
            "te parle, prévient-le que la plateforme n'a pas de node disponible."
        )

    lines = [f"État du cluster Spouet ({len(nodes)} node(s) en ligne) :"]
    for n in nodes[:6]:
        bits = [f"- {n.name}"]
        if n.gpu_model:
            bits.append(n.gpu_model)
        if n.vram_total_mb:
            used = n.vram_used_mb if n.vram_used_mb is not None else 0
            bits.append(f"VRAM {used}/{n.vram_total_mb} MB")
        lines.append(" · ".join(bits))
    if len(nodes) > 6:
        lines.append(f"… et {len(nodes) - 6} autre(s).")
    lines.append(
        f"{total_models} modèle(s) distinct(s) disponibles, "
        f"{enabled_tools} tool(s) sandbox actif(s)."
    )
    return "\n".join(lines)
