"""WebSocket que les *connectors persistants* ouvrent vers le backend.

Auth via query-param ``token`` (haché et comparé à ``connectors.auth_token_hash``)
puis l'``id`` du connector dans le path. Le canal est full-duplex :

- inbound  (connector → backend) : ``{"kind": "message" | "ping", ...}``
- outbound (backend → connector) : commandes publiées via Redis sur
  ``connector:{id}:outbound`` (``send_message``, ``typing``, ``react``, …)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from spouet.connectors.bridge import handle_inbound_event
from spouet.core.logging import get_logger
from spouet.core.security import hash_token
from spouet.db import async_session_factory
from spouet.db.models import Connector
from spouet.realtime.hub import (
    connector_inbound_channel,
    connector_outbound_channel,
    publish,
    subscribe,
)

router = APIRouter()
logger = get_logger(__name__)


@router.websocket("/{connector_id}")
async def connector_socket(
    ws: WebSocket, connector_id: str, token: str | None = None
) -> None:
    if not token:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        cid = UUID(connector_id)
    except ValueError:
        await ws.close(code=status.WS_1003_UNSUPPORTED_DATA)
        return

    async with async_session_factory()() as db:
        connector = await db.get(Connector, cid)
        if connector is None or not connector.enabled:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        if connector.auth_token_hash != hash_token(token):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await ws.accept()
    out_channel = connector_outbound_channel(cid)
    in_channel = connector_inbound_channel(cid)
    logger.info("connector.ws_connected", connector_id=str(cid))

    async def reader() -> None:
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = str(payload.get("kind") or "")
                async with async_session_factory()() as db2:
                    conn = await db2.get(Connector, cid)
                    if conn is None:
                        return
                    conn.last_heartbeat = datetime.now(timezone.utc)
                    if conn.status != "running":
                        conn.status = "running"
                    await db2.commit()
                    try:
                        await handle_inbound_event(db2, conn, kind=kind, payload=payload)
                    except Exception:  # noqa: BLE001
                        logger.exception("connector.inbound_failed")
                # Echo supervision UI
                await publish(in_channel, kind, payload)
        except WebSocketDisconnect:
            return

    async def writer() -> None:
        async for ev in subscribe(out_channel):
            if ev["event"] == "_idle":
                continue
            try:
                await ws.send_json(
                    {"kind": ev["event"], **(ev.get("data") or {})}
                )
            except Exception:  # noqa: BLE001
                return

    reader_task = asyncio.create_task(reader())
    writer_task = asyncio.create_task(writer())
    try:
        _, pending = await asyncio.wait(
            {reader_task, writer_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
    finally:
        async with async_session_factory()() as db3:
            conn = await db3.get(Connector, cid)
            if conn is not None and conn.status == "running":
                conn.status = "stopped"
                await db3.commit()
        with contextlib.suppress(Exception):
            await ws.close()
        logger.info("connector.ws_disconnected", connector_id=str(cid))
