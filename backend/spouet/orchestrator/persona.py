"""Personnalité « Spouet ».

Construit un system prompt qui donne à l'IA conscience d'elle-même : son nom,
le node sur lequel elle s'exécute, le modèle Ollama actif, ses ressources et
les capacités de la plateforme. Injecté au premier tour via build_extra_system.

Si l'utilisateur a renseigné des memories pinned (`ia_nom`, `prenom`,
`ia_emoji_totem`, etc. — typiquement remplies via l'onboarding mémoire),
elles surchargent la persona par défaut.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.config import settings
from spouet.db.models import Memory, Model, Node, Tool

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
    user_id: UUID | None = None,
) -> str:
    """Construit le system prompt complet en prenant en compte l'état du cluster.

    `node_name` / `model_name` : si fournis, le prompt mentionne explicitement
    où la requête s'exécute (à passer après pick_node). Sinon, on liste l'état
    global du cluster.
    `user_id` : si fourni, on intègre l'identité personnalisée (memories pinned).
    """
    pinned_kv = await _pinned_identity(db, user_id) if user_id else {}
    parts: list[str] = [_personalize_base(pinned_kv)]

    identity = _identity_block(pinned_kv)
    if identity:
        parts.append(identity)

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


async def _pinned_identity(db: AsyncSession, user_id: UUID) -> dict[str, str]:
    rows = (
        await db.execute(
            select(Memory).where(Memory.user_id == user_id, Memory.pinned.is_(True))
        )
    ).scalars().all()
    return {m.key: m.value for m in rows if m.key and m.value}


def _personalize_base(kv: dict[str, str]) -> str:
    """Si l'utilisateur a renommé l'IA via `ia_nom`, on remplace 'Spouet' dans
    la persona de base. Reste minimaliste : on ne re-rédige pas tout."""
    name = (kv.get("ia_nom") or "").strip()
    if not name or name.lower() == PERSONA_NAME.lower():
        return BASE_PERSONA
    return BASE_PERSONA.replace("Spouet", name, 1)


def _identity_block(kv: dict[str, str]) -> str | None:
    """Bloc compact (max ~6 lignes) injecté pour personnaliser le ton et la
    signature. Rien si rien n'est défini → garde le contexte minimal."""
    lines: list[str] = []
    prenom = (kv.get("prenom") or "").strip()
    if prenom:
        lines.append(f"L'utilisateur s'appelle {prenom}.")
    role = (kv.get("role_utilisateur") or "").strip()
    if role:
        lines.append(f"Contexte utilisateur : {role}.")
    langue = (kv.get("langue") or "").strip()
    if langue and langue.lower() not in {"français", "francais", "fr"}:
        lines.append(f"Langue préférée : {langue}.")
    ton = (kv.get("ton") or "").strip()
    if ton:
        lines.append(f"Ton attendu : {ton}.")
    totem = (kv.get("ia_emoji_totem") or "").strip()
    if totem:
        lines.append(
            f"Termine systématiquement chacune de tes réponses par l'émoji {totem} (ton totem)."
        )
    return "\n".join(lines) if lines else None


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
