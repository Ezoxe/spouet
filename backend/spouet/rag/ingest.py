"""Pipeline d'ingestion : parse → chunk → embed → persist."""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.logging import get_logger
from spouet.db.models import Document, DocumentChunk
from spouet.rag.chunker import chunk_text
from spouet.rag.embedder import embed_texts

logger = get_logger(__name__)


def _extract_text(filename: str, mime: str, raw: bytes) -> str:
    name_lower = filename.lower()
    if mime in ("text/plain", "text/markdown") or name_lower.endswith((".txt", ".md")):
        return raw.decode("utf-8", errors="replace")
    if mime == "application/pdf" or name_lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            return "\n\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception as e:  # noqa: BLE001
            logger.warning("pdf.extract_failed", error=str(e))
            return ""
    # Fallback : tente UTF-8
    return raw.decode("utf-8", errors="replace")


async def ingest_document(
    db: AsyncSession,
    *,
    user_id: UUID,
    filename: str,
    mime: str,
    raw: bytes,
) -> Document:
    """Ingère un document : crée Document, chunks + embeddings, marque ready."""
    digest = hashlib.sha256(raw).hexdigest()
    existing = await db.scalar(select(Document).where(Document.hash == digest))
    if existing is not None:
        return existing

    doc = Document(
        user_id=user_id,
        source=filename,
        mime=mime,
        title=filename,
        bytes=len(raw),
        hash=digest,
        status="processing",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    try:
        text = _extract_text(filename, mime, raw)
        chunks = chunk_text(text)
        if not chunks:
            doc.status = "empty"
            await db.commit()
            return doc

        embeddings = await embed_texts(db, [c.text for c in chunks])
        if len(embeddings) != len(chunks):
            raise RuntimeError(f"embedding count mismatch ({len(embeddings)} vs {len(chunks)})")

        for c, vec in zip(chunks, embeddings, strict=True):
            db.add(
                DocumentChunk(
                    document_id=doc.id,
                    chunk_idx=c.idx,
                    text=c.text,
                    tokens=c.tokens,
                    embedding=vec,
                    created_at=datetime.now(timezone.utc),
                )
            )
        doc.status = "ready"
        await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.exception("ingest.failed", doc=str(doc.id))
        doc.status = "failed"
        await db.commit()
        raise

    return doc
