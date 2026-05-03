"""Routes RAG : upload + listing + search."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.core.config import settings
from spouet.db.models import Document
from spouet.rag.ingest import ingest_document
from spouet.rag.retriever import search

router = APIRouter()


class DocumentOut(BaseModel):
    id: str
    title: str
    source: str
    mime: str
    bytes: int
    status: str
    created_at: datetime


class HitOut(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    text: str
    distance: float


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(user: CurrentUser, db: DbSession) -> list[DocumentOut]:
    rows = (
        await db.execute(
            select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())
        )
    ).scalars().all()
    return [_to_out(d) for d in rows]


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile, user: CurrentUser, db: DbSession
) -> DocumentOut:
    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(raw) > settings.upload_max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")
    doc = await ingest_document(
        db,
        user_id=user.id,
        filename=file.filename or "file",
        mime=file.content_type or "application/octet-stream",
        raw=raw,
    )
    return _to_out(doc)


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(doc_id: UUID, user: CurrentUser, db: DbSession) -> None:
    doc = await db.get(Document, doc_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await db.delete(doc)
    await db.commit()


@router.get("/search", response_model=list[HitOut])
async def search_documents(
    q: str, user: CurrentUser, db: DbSession, k: int = 6
) -> list[HitOut]:
    if not q.strip():
        return []
    hits = await search(db, user_id=user.id, query=q, k=max(1, min(k, 30)))
    return [
        HitOut(
            chunk_id=str(h.chunk_id),
            document_id=str(h.document_id),
            document_title=h.document_title,
            text=h.text,
            distance=h.distance,
        )
        for h in hits
    ]


def _to_out(d: Document) -> DocumentOut:
    return DocumentOut(
        id=str(d.id),
        title=d.title or d.source,
        source=d.source,
        mime=d.mime,
        bytes=d.bytes,
        status=d.status,
        created_at=d.created_at,
    )
