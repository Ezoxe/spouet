"""Pont d'exécution des actions desktop côté client (app Tauri).

L'orchestrator publie une demande d'action sur le canal ``user:{id}`` et attend
le résultat — exactement le pattern HITL de ``tools/approval.py``. Ici c'est le
client Tauri (qui tient une connexion SSE persistante sur ``/sse/user``) qui
exécute l'action localement, puis POST le résultat sur
``/api/desktop/actions/{id}/result``.

Pourquoi pas un tool Docker : un conteneur serveur ne peut pas toucher le bureau
Windows de l'utilisateur. L'exécution doit avoir lieu sur la machine cliente.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from uuid import UUID

import redis.asyncio as redis

from spouet.core.config import settings
from spouet.core.logging import get_logger
from spouet.realtime.hub import publish, user_channel

logger = get_logger(__name__)

# Une action desktop doit aboutir vite ; au-delà on considère le client absent.
_TTL = 120


def _client() -> redis.Redis:
    return redis.from_url(str(settings.redis_url), decode_responses=True)


def _key(request_id: str) -> str:
    return f"desktop:req:{request_id}"


async def request_action(user_id: UUID | str, action: dict[str, Any]) -> str:
    """Crée une demande d'action et la pousse au client via le canal user.

    ``action`` = ``{"action": "launch_app"|"open_url"|..., ...params}``. Retourne
    le ``request_id`` à attendre via :func:`wait_for_result`.
    """
    rid = str(uuid.uuid4())
    cli = _client()
    try:
        await cli.set(
            _key(rid),
            json.dumps({"status": "pending", "action": action}, ensure_ascii=False),
            ex=_TTL,
        )
    finally:
        await cli.aclose()
    # Push au client (Tauri) abonné à user:{id}
    await publish(
        user_channel(user_id),
        "desktop_action",
        {"request_id": rid, "action": action},
    )
    return rid


async def submit_result(request_id: str, result: dict[str, Any]) -> bool:
    """Le client renvoie le résultat. True si la demande existait (non expirée)."""
    cli = _client()
    try:
        raw = await cli.get(_key(request_id))
        if raw is None:
            return False
        data = json.loads(raw)
        data["status"] = "done"
        data["result"] = result
        await cli.set(_key(request_id), json.dumps(data, ensure_ascii=False), ex=_TTL)
        return True
    finally:
        await cli.aclose()


async def wait_for_result(
    request_id: str, *, poll_s: float = 0.25, timeout_s: float = 60.0
) -> dict[str, Any]:
    """Bloque jusqu'au résultat renvoyé par le client.

    Retourne le dict ``result`` du client, ou ``{"status": "timeout"|"expired"}``
    si le client n'a pas répondu (typiquement : app desktop non connectée).
    """
    cli = _client()
    try:
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            raw = await cli.get(_key(request_id))
            if raw is None:
                return {"status": "expired", "error": "requête desktop expirée"}
            data = json.loads(raw)
            if data.get("status") == "done":
                return data.get("result") or {"status": "ok"}
            await asyncio.sleep(poll_s)
        return {
            "status": "timeout",
            "error": "le client desktop n'a pas répondu à temps",
        }
    finally:
        await cli.aclose()
