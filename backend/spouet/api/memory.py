"""Routes memory long-terme."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.db.models import Memory
from spouet.memory import files as memory_files
from spouet.memory.store import upsert as upsert_memory
from spouet.memory.templates import MEMORY_TEMPLATES

router = APIRouter()


# ---------------------------------------------------------------------------
# Mémoire « fichiers .md » (long-terme lue à la demande par l'IA)
# ---------------------------------------------------------------------------


class MemoryFileOut(BaseModel):
    name: str
    title: str
    description: str
    size_bytes: int
    updated_at: str


class MemoryFileContentOut(BaseModel):
    name: str
    content: str


class MemoryFileWrite(BaseModel):
    content: str = Field(min_length=1)


class MemoryTemplateOut(BaseModel):
    name: str
    title: str
    description: str
    content: str
    active: bool


@router.get("/templates", response_model=list[MemoryTemplateOut])
async def list_memory_templates(user: CurrentUser) -> list[MemoryTemplateOut]:
    """Modèles `.md` prêts à l'emploi + s'ils sont déjà activés (fichier existant)."""
    active = {f.name for f in memory_files.list_files(user.id)}
    return [
        MemoryTemplateOut(
            name=t.name,
            title=t.title,
            description=t.description,
            content=t.content,
            active=t.name in active,
        )
        for t in MEMORY_TEMPLATES
    ]


@router.get("/files", response_model=list[MemoryFileOut])
async def list_memory_files(user: CurrentUser) -> list[MemoryFileOut]:
    return [MemoryFileOut(**f.__dict__) for f in memory_files.list_files(user.id)]


@router.get("/files/{name}", response_model=MemoryFileContentOut)
async def read_memory_file(name: str, user: CurrentUser) -> MemoryFileContentOut:
    content = memory_files.read_file(user.id, name)
    if content is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return MemoryFileContentOut(name=memory_files.slugify(name), content=content)


@router.put("/files/{name}", response_model=MemoryFileOut)
async def write_memory_file(name: str, payload: MemoryFileWrite, user: CurrentUser) -> MemoryFileOut:
    try:
        f = memory_files.write_file(user.id, name, payload.content)
    except memory_files.MemoryFileError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return MemoryFileOut(**f.__dict__)


@router.delete("/files/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory_file(name: str, user: CurrentUser) -> None:
    if not memory_files.delete_file(user.id, name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


class MemoryUpsert(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1)
    pinned: bool | None = None


class MemoryPatch(BaseModel):
    pinned: bool | None = None
    value: str | None = Field(default=None, min_length=1)


class MemoryOut(BaseModel):
    id: str
    key: str
    value: str
    score: float
    pinned: bool
    created_at: datetime
    last_used_at: datetime | None


@router.get("", response_model=list[MemoryOut])
async def list_memories(user: CurrentUser, db: DbSession) -> list[MemoryOut]:
    rows = (
        await db.execute(
            select(Memory).where(Memory.user_id == user.id).order_by(Memory.created_at.desc())
        )
    ).scalars().all()
    return [_to_out(m) for m in rows]


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_or_update(payload: MemoryUpsert, user: CurrentUser, db: DbSession) -> MemoryOut:
    mem = await upsert_memory(
        db,
        user_id=user.id,
        key=payload.key,
        value=payload.value,
        pinned=payload.pinned,
    )
    return _to_out(mem)


@router.patch("/{memory_id}", response_model=MemoryOut)
async def patch_memory(
    memory_id: UUID, payload: MemoryPatch, user: CurrentUser, db: DbSession
) -> MemoryOut:
    mem = await db.get(Memory, memory_id)
    if mem is None or mem.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if payload.pinned is not None:
        mem.pinned = payload.pinned
    if payload.value is not None:
        # Re-upsert pour réembedder la nouvelle valeur
        mem = await upsert_memory(
            db,
            user_id=user.id,
            key=mem.key,
            value=payload.value,
            pinned=mem.pinned,
        )
    else:
        await db.commit()
        await db.refresh(mem)
    return _to_out(mem)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: UUID, user: CurrentUser, db: DbSession) -> None:
    mem = await db.get(Memory, memory_id)
    if mem is None or mem.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await db.delete(mem)
    await db.commit()


def _to_out(m: Memory) -> MemoryOut:
    return MemoryOut(
        id=str(m.id),
        key=m.key,
        value=m.value,
        score=m.score,
        pinned=m.pinned,
        created_at=m.created_at,
        last_used_at=m.last_used_at,
    )
