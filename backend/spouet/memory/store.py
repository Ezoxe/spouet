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
    db: AsyncSession, *, user_id: UUID, key: str, value: str
) -> Memory:
    existing = await db.scalar(
        select(Memory).where(Memory.user_id == user_id, Memory.key == key)
    )
    try:
        vec = await embed_one(db, f"{key}: {value}")
    except Exception as e:  # noqa: BLE001
        logger.warning("memory.embed_failed", error=str(e))
        vec = None

    if existing is None:
        mem = Memory(user_id=user_id, key=key, value=value, embedding=vec)
        db.add(mem)
    else:
        existing.value = value
        existing.embedding = vec
        mem = existing
    await db.commit()
    await db.refresh(mem)
    return mem


async def recall_relevant(
    db: AsyncSession, *, user_id: UUID, query: str, k: int = 5
) -> list[Memory]:
    """Top-k memories les plus proches sémantiquement de `query`.

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
                .where(Memory.user_id == user_id, Memory.embedding.is_not(None))
                .order_by(distance)
                .limit(k)
            )
        ).scalars().all()
    else:
        # Fallback : top par score
        rows = (
            await db.execute(
                select(Memory)
                .where(Memory.user_id == user_id)
                .order_by(Memory.score.desc())
                .limit(k)
            )
        ).scalars().all()

    now = datetime.now(timezone.utc)
    for m in rows:
        m.last_used_at = now
    await db.commit()
    return list(rows)
