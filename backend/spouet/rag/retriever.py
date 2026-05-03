"""Recherche sémantique dans les chunks (PGVector cosine)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.db.models import Document, DocumentChunk
from spouet.rag.embedder import embed_one


@dataclass
class Hit:
    chunk_id: UUID
    document_id: UUID
    document_title: str
    text: str
    distance: float


async def search(db: AsyncSession, *, user_id: UUID, query: str, k: int = 6) -> list[Hit]:
    """Top-k chunks les plus proches du `query` pour ce user."""
    if not query.strip():
        return []
    q_vec = await embed_one(db, query)
    if not q_vec:
        return []

    distance = DocumentChunk.embedding.cosine_distance(q_vec)
    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.text,
            distance.label("dist"),
            Document.title,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.user_id == user_id, Document.status == "ready")
        .order_by("dist")
        .limit(k)
    )
    rows = (await db.execute(stmt)).all()
    return [
        Hit(
            chunk_id=r.id,
            document_id=r.document_id,
            document_title=r.title,
            text=r.text,
            distance=float(r.dist),
        )
        for r in rows
    ]


def format_for_prompt(hits: list[Hit], max_chars: int = 4000) -> str:
    """Format compact pour injection en system prompt."""
    if not hits:
        return ""
    out: list[str] = ["Contexte (extraits pertinents) :"]
    used = 0
    for i, h in enumerate(hits, 1):
        snippet = h.text.strip()
        block = f"[{i}] {h.document_title}\n{snippet}"
        if used + len(block) > max_chars:
            break
        out.append(block)
        used += len(block)
    return "\n\n".join(out)
