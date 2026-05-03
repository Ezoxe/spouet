"""Routes memory long-terme."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.db.models import Memory
from spouet.memory.store import upsert as upsert_memory

router = APIRouter()


class MemoryUpsert(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1)


class MemoryOut(BaseModel):
    id: str
    key: str
    value: str
    score: float
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
    mem = await upsert_memory(db, user_id=user.id, key=payload.key, value=payload.value)
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
        created_at=m.created_at,
        last_used_at=m.last_used_at,
    )
