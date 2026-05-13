"""Routes conversations + chat (streaming SSE)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.db.models import Conversation, Message
from spouet.orchestrator.chat_loop import stream_assistant_reply

router = APIRouter()


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=255)
    system_prompt: str | None = None
    model_pref: str | None = None


class ConversationOut(BaseModel):
    id: str
    title: str
    system_prompt: str | None
    model_pref: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=list[ConversationOut])
async def list_conversations(user: CurrentUser, db: DbSession) -> list[ConversationOut]:
    rows = (
        await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user.id, Conversation.archived.is_(False))
            .order_by(Conversation.updated_at.desc())
        )
    ).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate, user: CurrentUser, db: DbSession
) -> ConversationOut:
    conv = Conversation(
        user_id=user.id,
        title=payload.title,
        system_prompt=payload.system_prompt,
        model_pref=payload.model_pref,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return _to_out(conv)


@router.get("/{conv_id}", response_model=ConversationOut)
async def get_conversation(conv_id: UUID, user: CurrentUser, db: DbSession) -> ConversationOut:
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return _to_out(conv)


@router.delete("/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conv_id: UUID, user: CurrentUser, db: DbSession) -> None:
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await db.delete(conv)
    await db.commit()


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    model_used: str | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int | None
    ttft_ms: int | None = None
    finish_reason: str | None = None
    content_json: dict[str, Any] | None = None
    created_at: datetime


class ChatRequest(BaseModel):
    text: str = Field(min_length=1)
    model: str | None = None


@router.get("/{conv_id}/messages", response_model=list[MessageOut])
async def list_messages(conv_id: UUID, user: CurrentUser, db: DbSession) -> list[MessageOut]:
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()
    return [
        MessageOut(
            id=str(m.id),
            role=m.role,
            content=m.content,
            model_used=m.model_used,
            tokens_in=m.tokens_in,
            tokens_out=m.tokens_out,
            latency_ms=m.latency_ms,
            ttft_ms=m.ttft_ms,
            finish_reason=m.finish_reason,
            content_json=m.content_json,
            created_at=m.created_at,
        )
        for m in rows
    ]


@router.post("/{conv_id}/messages")
async def send_message(
    conv_id: UUID, payload: ChatRequest, user: CurrentUser, db: DbSession
) -> StreamingResponse:
    """Envoie un message user et stream la réponse assistant en SSE."""
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    async def gen() -> AsyncIterator[bytes]:
        async for ev in stream_assistant_reply(
            db,
            conversation=conv,
            user_text=payload.text,
            model_override=payload.model,
        ):
            data = json.dumps(ev["data"], ensure_ascii=False, default=str)
            lines = "\n".join(f"data: {ln}" for ln in data.split("\n"))
            yield f"event: {ev['event']}\n{lines}\n\n".encode()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _to_out(c: Conversation) -> ConversationOut:
    return ConversationOut(
        id=str(c.id),
        title=c.title,
        system_prompt=c.system_prompt,
        model_pref=c.model_pref,
        archived=c.archived,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )
