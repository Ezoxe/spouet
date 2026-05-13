"""Stream SSE temps réel branché sur Redis pub/sub."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.db.models import Conversation, Node
from spouet.realtime.hub import conv_channel, node_metrics_channel, subscribe, user_channel

router = APIRouter()


def _format_sse(event: str, data: str) -> bytes:
    # Les chaînes multi-lignes doivent être préfixées "data: " sur chaque ligne
    lines = "\n".join(f"data: {ln}" for ln in data.split("\n"))
    return f"event: {event}\n{lines}\n\n".encode()


@router.get("/user")
async def user_events(user: CurrentUser) -> StreamingResponse:
    """Events globaux du user (notifs, sync multi-device, status nodes)."""
    return StreamingResponse(
        _stream(user_channel(user.id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations/{conv_id}")
async def conv_events(conv_id: UUID, user: CurrentUser, db: DbSession) -> StreamingResponse:
    """Events d'une conversation (tokens stream, status, tool_call)."""
    conv = await db.get(Conversation, conv_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return StreamingResponse(
        _stream(conv_channel(conv_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/nodes/{node_id}/metrics")
async def node_metrics_stream(
    node_id: UUID, _: CurrentUser, db: DbSession
) -> StreamingResponse:
    """Stream live des heartbeats d'un node (remplace le polling à 3s)."""
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    return StreamingResponse(
        _stream(node_metrics_channel(node_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream(*channels: str) -> AsyncIterator[bytes]:
    import json

    yield _format_sse("hello", json.dumps({"channels": list(channels)}))
    async for ev in subscribe(*channels):
        if ev["event"] == "_idle":
            yield b": keepalive\n\n"
            continue
        yield _format_sse(ev["event"], json.dumps(ev["data"], ensure_ascii=False, default=str))
