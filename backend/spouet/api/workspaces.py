"""Routes workspaces multi-agents."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.api.deps import CurrentUser, DbSession
from spouet.db.models import Conversation, WorkspaceSession
from spouet.realtime.hub import subscribe, workspace_channel

router = APIRouter()


# ---------------------------------------------------------------------------
# Schémas
# ---------------------------------------------------------------------------


class WorkerConfig(BaseModel):
    title: str = Field(default="Worker", max_length=255)
    model_pref: str
    system_prompt: str | None = None
    allowed_tool_slugs: list[str] = Field(default_factory=list)


class WorkspaceCreate(BaseModel):
    name: str = Field(default="New workspace", max_length=255)
    manager_model: str
    manager_system_prompt: str | None = None
    workers: list[WorkerConfig] = Field(default_factory=list)


class ConversationRef(BaseModel):
    id: str
    title: str
    workspace_role: str
    model_pref: str | None
    created_at: datetime


class WorkspaceOut(BaseModel):
    id: str
    name: str
    conversations: list[ConversationRef]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(user: CurrentUser, db: DbSession) -> list[WorkspaceOut]:
    rows = (
        await db.execute(
            select(WorkspaceSession)
            .where(WorkspaceSession.user_id == user.id)
            .order_by(WorkspaceSession.created_at.desc())
        )
    ).scalars().all()
    result = []
    for ws in rows:
        convs = await _load_conversations(db, ws.id)
        result.append(_to_out(ws, convs))
    return result


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate, user: CurrentUser, db: DbSession
) -> WorkspaceOut:
    ws = WorkspaceSession(user_id=user.id, name=payload.name)
    db.add(ws)
    await db.flush()

    manager = Conversation(
        user_id=user.id,
        title=f"[Manager] {payload.name}",
        model_pref=payload.manager_model,
        system_prompt=payload.manager_system_prompt,
        workspace_id=ws.id,
        workspace_role="manager",
    )
    db.add(manager)

    for w in payload.workers:
        worker = Conversation(
            user_id=user.id,
            title=w.title,
            model_pref=w.model_pref,
            system_prompt=w.system_prompt,
            workspace_id=ws.id,
            workspace_role="worker",
            allowed_tool_slugs=w.allowed_tool_slugs,
        )
        db.add(worker)

    await db.commit()
    await db.refresh(ws)
    convs = await _load_conversations(db, ws.id)
    return _to_out(ws, convs)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: UUID, user: CurrentUser, db: DbSession
) -> WorkspaceOut:
    ws = await db.get(WorkspaceSession, workspace_id)
    if ws is None or ws.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    convs = await _load_conversations(db, ws.id)
    return _to_out(ws, convs)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: UUID, user: CurrentUser, db: DbSession
) -> None:
    ws = await db.get(WorkspaceSession, workspace_id)
    if ws is None or ws.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await db.delete(ws)
    await db.commit()


@router.get("/{workspace_id}/stream")
async def stream_workspace(
    workspace_id: UUID, user: CurrentUser, db: DbSession
) -> StreamingResponse:
    """SSE aggregant tous les events workers du workspace."""
    ws = await db.get(WorkspaceSession, workspace_id)
    if ws is None or ws.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    channel = workspace_channel(workspace_id)

    async def gen() -> AsyncIterator[bytes]:
        async for ev in subscribe(channel):
            if ev["event"] == "_idle":
                yield b": keepalive\n\n"
                continue
            data = json.dumps(ev["data"], ensure_ascii=False, default=str)
            yield f"event: {ev['event']}\ndata: {data}\n\n".encode()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_conversations(
    db: AsyncSession, workspace_id: UUID
) -> list[Conversation]:
    return (
        await db.execute(
            select(Conversation)
            .where(Conversation.workspace_id == workspace_id)
            .order_by(Conversation.created_at.asc())
        )
    ).scalars().all()


def _to_out(ws: WorkspaceSession, convs: list[Conversation]) -> WorkspaceOut:
    return WorkspaceOut(
        id=str(ws.id),
        name=ws.name,
        conversations=[
            ConversationRef(
                id=str(c.id),
                title=c.title,
                workspace_role=c.workspace_role or "worker",
                model_pref=c.model_pref,
                created_at=c.created_at,
            )
            for c in convs
        ],
        created_at=ws.created_at,
        updated_at=ws.updated_at,
    )
