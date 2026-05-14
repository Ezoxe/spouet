"""Routes conversations + chat (streaming SSE)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, or_, select

from spouet.api.deps import CurrentUser, DbSession
from spouet.core.logging import get_logger
from spouet.db.models import Conversation, Message
from spouet.orchestrator.chat_loop import stream_assistant_reply

logger = get_logger(__name__)

router = APIRouter()


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=255)
    system_prompt: str | None = None
    model_pref: str | None = None


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    system_prompt: str | None = None
    model_pref: str | None = None
    allowed_tool_slugs: list[str] | None = None
    archived: bool | None = None


class ConversationOut(BaseModel):
    id: str
    title: str
    system_prompt: str | None
    model_pref: str | None
    archived: bool
    allowed_tool_slugs: list[str] = []
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    user: CurrentUser,
    db: DbSession,
    q: str | None = Query(default=None, description="Filtre full-text sur titre + messages"),
) -> list[ConversationOut]:
    query = (
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.archived.is_(False))
        .order_by(Conversation.updated_at.desc())
    )
    if q:
        # ILIKE sur title ou existence d'un message qui matche
        like = f"%{q}%"
        sub = (
            select(Message.conversation_id)
            .where(Message.content.ilike(like))
            .scalar_subquery()
        )
        query = query.where(or_(Conversation.title.ilike(like), Conversation.id.in_(sub)))
    rows = (await db.execute(query)).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate, user: CurrentUser, db: DbSession
) -> ConversationOut:
    conv = Conversation(
        user_id=user.id,
        title=payload.title,
        system_prompt=payload.system_prompt,
        model_pref=payload.model_pref or user.default_model,
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


@router.patch("/{conv_id}", response_model=ConversationOut)
async def patch_conversation(
    conv_id: UUID, payload: ConversationPatch, user: CurrentUser, db: DbSession
) -> ConversationOut:
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if payload.title is not None:
        conv.title = payload.title
    if payload.system_prompt is not None:
        # chaîne vide ⇒ on remet à None pour distinguer "pas défini"
        conv.system_prompt = payload.system_prompt or None
    if payload.model_pref is not None:
        conv.model_pref = payload.model_pref or None
    if payload.allowed_tool_slugs is not None:
        conv.allowed_tool_slugs = list(payload.allowed_tool_slugs)
    if payload.archived is not None:
        conv.archived = payload.archived
    await db.commit()
    await db.refresh(conv)
    return _to_out(conv)


@router.delete("/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conv_id: UUID, user: CurrentUser, db: DbSession) -> None:
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await db.delete(conv)
    await db.commit()


@router.get("/{conv_id}/export", response_class=PlainTextResponse)
async def export_conversation(
    conv_id: UUID, user: CurrentUser, db: DbSession
) -> PlainTextResponse:
    """Export markdown — titre + messages dans l'ordre. Inclut les messages tool."""
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    msgs = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()
    lines: list[str] = [f"# {conv.title}", ""]
    if conv.model_pref:
        lines.append(f"_Modèle : `{conv.model_pref}`_")
        lines.append("")
    if conv.system_prompt:
        lines.append("## System prompt")
        lines.append("")
        lines.append(conv.system_prompt)
        lines.append("")
    for m in msgs:
        role_label = {
            "user": "👤 **Vous**",
            "assistant": f"🤖 **{m.model_used or 'Assistant'}**",
            "tool": "🔧 **Tool**",
            "system": "⚙️ **Système**",
        }.get(m.role, f"**{m.role}**")
        ts = m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else ""
        lines.append(f"### {role_label} — _{ts}_")
        lines.append("")
        lines.append(m.content or "_(vide)_")
        lines.append("")
    body = "\n".join(lines)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in conv.title)[:80] or "conversation"
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.md"'},
    )


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

    def _format_event(event: str, data: Any) -> bytes:
        payload = json.dumps(data, ensure_ascii=False, default=str)
        lines = "\n".join(f"data: {ln}" for ln in payload.split("\n"))
        return f"event: {event}\n{lines}\n\n".encode()

    async def gen() -> AsyncIterator[bytes]:
        # On enveloppe la boucle complète dans un try/except :
        #
        # 1. Sans ça, toute exception levée par stream_assistant_reply (ou
        #    par json.dumps sur un payload incompatible) fait avorter le
        #    StreamingResponse en plein chunk, ce qui produit côté client
        #    un `ERR_INCOMPLETE_CHUNKED_ENCODING` opaque sans message.
        # 2. On émet un `event: error` propre avant de clore le flux, et
        #    on log l'exception pour pouvoir l'investiguer.
        try:
            async for ev in stream_assistant_reply(
                db,
                conversation=conv,
                user_text=payload.text,
                model_override=payload.model,
            ):
                yield _format_event(ev["event"], ev["data"])
        except Exception as e:  # noqa: BLE001
            logger.exception(
                "chat.stream_failed",
                conv_id=str(conv_id),
                error=str(e),
                error_type=type(e).__name__,
            )
            yield _format_event(
                "error",
                {"message": f"{type(e).__name__}: {e}"},
            )

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
        allowed_tool_slugs=list(c.allowed_tool_slugs or []),
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _format_sse(event: str, data: Any) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    body = "\n".join(f"data: {ln}" for ln in payload.split("\n"))
    return f"event: {event}\n{body}\n\n".encode()


async def _delete_messages_from(
    db: DbSession, conversation_id: UUID, from_created_at: datetime, *, inclusive: bool
) -> None:
    """Supprime tous les messages d'une conv créés à >= (inclusive) ou > (exclusif)
    de la timestamp fournie."""
    cond = (
        Message.created_at >= from_created_at
        if inclusive
        else Message.created_at > from_created_at
    )
    await db.execute(
        delete(Message).where(and_(Message.conversation_id == conversation_id, cond))
    )
    await db.commit()


class EditMessageRequest(BaseModel):
    text: str = Field(min_length=1)
    model: str | None = None


class RegenerateRequest(BaseModel):
    model: str | None = None


@router.post("/{conv_id}/regenerate")
async def regenerate_last(
    conv_id: UUID,
    user: CurrentUser,
    db: DbSession,
    payload: RegenerateRequest = Body(default_factory=RegenerateRequest),
) -> StreamingResponse:
    """Régénère la dernière réponse assistant.

    Supprime tous les messages postérieurs au dernier message user, puis stream
    une nouvelle réponse à partir de ce même message user.
    """
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    last_user = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id, Message.role == "user")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last_user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aucun message user à régénérer")

    await _delete_messages_from(db, conv_id, last_user.created_at, inclusive=False)

    model_override = payload.model

    async def gen() -> AsyncIterator[bytes]:
        try:
            async for ev in stream_assistant_reply(
                db,
                conversation=conv,
                user_text=last_user.content,
                model_override=model_override,
                skip_user_insert=True,
            ):
                yield _format_sse(ev["event"], ev["data"])
        except Exception as e:  # noqa: BLE001
            logger.exception("chat.regenerate_failed", conv_id=str(conv_id), error=str(e))
            yield _format_sse("error", {"message": f"{type(e).__name__}: {e}"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{conv_id}/messages/{msg_id}/edit")
async def edit_user_message(
    conv_id: UUID,
    msg_id: UUID,
    payload: EditMessageRequest,
    user: CurrentUser,
    db: DbSession,
) -> StreamingResponse:
    """Édite le contenu d'un message user et régénère la suite.

    Supprime tous les messages plus récents que celui édité puis stream une
    nouvelle réponse.
    """
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation introuvable")

    target = await db.get(Message, msg_id)
    if target is None or target.conversation_id != conv_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message introuvable")
    if target.role != "user":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Seuls les messages user sont éditables")

    target.content = payload.text
    await db.commit()
    await _delete_messages_from(db, conv_id, target.created_at, inclusive=False)

    async def gen() -> AsyncIterator[bytes]:
        try:
            async for ev in stream_assistant_reply(
                db,
                conversation=conv,
                user_text=payload.text,
                model_override=payload.model,
                skip_user_insert=True,
            ):
                yield _format_sse(ev["event"], ev["data"])
        except Exception as e:  # noqa: BLE001
            logger.exception("chat.edit_failed", conv_id=str(conv_id), error=str(e))
            yield _format_sse("error", {"message": f"{type(e).__name__}: {e}"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
