"""Memory long-terme : CRUD + recall sémantique."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.logging import get_logger
from spouet.db.models import Memory
from spouet.rag.embedder import embed_one

logger = get_logger(__name__)


async def upsert(
    db: AsyncSession,
    *,
    user_id: UUID,
    key: str,
    value: str,
    pinned: bool | None = None,
) -> Memory:
    """Insère ou met à jour une mémoire. Si `pinned` est None, on garde la
    valeur existante (ou False si nouveau)."""
    existing = await db.scalar(
        select(Memory).where(Memory.user_id == user_id, Memory.key == key)
    )
    try:
        vec = await embed_one(db, f"{key}: {value}")
    except Exception as e:  # noqa: BLE001
        logger.warning("memory.embed_failed", error=str(e))
        vec = None

    if existing is None:
        mem = Memory(
            user_id=user_id,
            key=key,
            value=value,
            embedding=vec,
            pinned=bool(pinned) if pinned is not None else False,
        )
        db.add(mem)
    else:
        existing.value = value
        existing.embedding = vec
        if pinned is not None:
            existing.pinned = pinned
        mem = existing
    await db.commit()
    await db.refresh(mem)
    return mem


async def list_pinned(db: AsyncSession, *, user_id: UUID) -> list[Memory]:
    """Mémoires épinglées : injectées systématiquement dans le system prompt.

    Convention : les clés courantes attendues par la persona sont
    `prenom`, `ia_nom`, `ia_emoji_totem`, `langue`, `ton`, `role_utilisateur`.
    """
    rows = (
        await db.execute(
            select(Memory)
            .where(Memory.user_id == user_id, Memory.pinned.is_(True))
            .order_by(Memory.key.asc())
        )
    ).scalars().all()
    return list(rows)


async def recall_relevant(
    db: AsyncSession, *, user_id: UUID, query: str, k: int = 5
) -> list[Memory]:
    """Top-k memories non-pinned les plus proches sémantiquement de `query`.

    Les pinned sont déjà chargées via `list_pinned` (toujours présentes), donc
    on les exclut ici pour ne pas doublonner et garder le contexte compact.
    Met à jour `last_used_at` pour les memories effectivement renvoyées.
    """
    if not query.strip():
        return []

    try:
        q_vec = await embed_one(db, query)
    except Exception:  # noqa: BLE001
        q_vec = None

    if q_vec:
        distance = Memory.embedding.cosine_distance(q_vec)
        rows = (
            await db.execute(
                select(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.embedding.is_not(None),
                    Memory.pinned.is_(False),
                )
                .order_by(distance)
                .limit(k)
            )
        ).scalars().all()
    else:
        # Fallback : top par score
        rows = (
            await db.execute(
                select(Memory)
                .where(Memory.user_id == user_id, Memory.pinned.is_(False))
                .order_by(Memory.score.desc())
                .limit(k)
            )
        ).scalars().all()

    now = datetime.now(timezone.utc)
    for m in rows:
        m.last_used_at = now
    await db.commit()
    return list(rows)
