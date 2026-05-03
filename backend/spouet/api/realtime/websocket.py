"""WebSocket : abonnement multi-canaux + envoi d'actions client (HITL approve/reject).

Auth via query-param `token` (les WS ne portent pas de header Authorization
de manière standard côté browser).
"""

from __future__ import annotations

import json
from contextlib import suppress
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from spouet.core.logging import get_logger
from spouet.core.security import hash_token
from spouet.db import async_session_factory
from spouet.db.models import Conversation, User
from spouet.realtime.hub import conv_channel, subscribe, user_channel

router = APIRouter()
logger = get_logger(__name__)


@router.websocket("/events")
async def events(ws: WebSocket, token: str | None = None, conv_id: str | None = None) -> None:
    if not token:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    async with async_session_factory()() as db:
        user = await db.scalar(
            select(User).where(User.api_token_hash == hash_token(token), User.is_active.is_(True))
        )
        if user is None:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        channels: list[str] = [user_channel(user.id)]
        if conv_id:
            try:
                cid = UUID(conv_id)
            except ValueError:
                await ws.close(code=status.WS_1003_UNSUPPORTED_DATA)
                return
            conv = await db.get(Conversation, cid)
            if conv is None or conv.user_id != user.id:
                await ws.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            channels.append(conv_channel(cid))

    await ws.accept()
    import asyncio

    async def reader() -> None:
        try:
            while True:
                raw = await ws.receive_text()
                with suppress(json.JSONDecodeError):
                    data = json.loads(raw)
                    logger.info("ws.client_msg", user=str(user.id), msg=data)
                    # M3 : route les actions HITL (approve/reject) via Redis
        except WebSocketDisconnect:
            return

    async def writer() -> None:
        async for ev in subscribe(*channels):
            if ev["event"] == "_idle":
                continue
            try:
                await ws.send_json(ev)
            except Exception:  # noqa: BLE001
                return

    reader_task = asyncio.create_task(reader())
    writer_task = asyncio.create_task(writer())
    done, pending = await asyncio.wait(
        {reader_task, writer_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for t in pending:
        t.cancel()
        with suppress(asyncio.CancelledError):
            await t
    with suppress(Exception):
        await ws.close()
