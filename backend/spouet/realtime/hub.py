"""Hub temps réel : Redis pub/sub, broadcast vers SSE et WS.

Conventions de canaux :
- `conv:{conversation_id}`  → events liés à une conversation (tokens stream, status, tool_call, etc.)
- `user:{user_id}`           → events globaux pour ce user (notifs, jobs, multi-device sync)
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import redis.asyncio as redis

from spouet.core.config import settings
from spouet.core.logging import get_logger

logger = get_logger(__name__)


_pub_client: redis.Redis | None = None


def _get_pub() -> redis.Redis:
    global _pub_client
    if _pub_client is None:
        _pub_client = redis.from_url(str(settings.redis_url), decode_responses=True)
    return _pub_client


def conv_channel(conv_id: UUID | str) -> str:
    return f"conv:{conv_id}"


def user_channel(user_id: UUID | str) -> str:
    return f"user:{user_id}"


def connector_outbound_channel(connector_id: UUID | str) -> str:
    """Canal sur lequel le backend publie les commandes destinées au connector
    (envoyer un message Discord, ajouter un emoji, etc.)."""
    return f"connector:{connector_id}:outbound"


def connector_inbound_channel(connector_id: UUID | str) -> str:
    """Canal sur lequel le backend publie un écho des events reçus du connector
    (utile pour la supervision UI)."""
    return f"connector:{connector_id}:inbound"


def workspace_channel(workspace_id: UUID | str) -> str:
    return f"workspace:{workspace_id}"


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


async def publish(channel: str, event: str, data: Any) -> None:
    """Publie un event sur un canal. `data` doit être JSON-sérialisable."""
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str)
    try:
        await _get_pub().publish(channel, payload)
    except Exception as e:  # noqa: BLE001
        logger.warning("hub.publish_failed", channel=channel, error=str(e))


async def publish_many(channels: list[str], event: str, data: Any) -> None:
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str)
    pub = _get_pub()
    pipe = pub.pipeline()
    for ch in channels:
        pipe.publish(ch, payload)
    await pipe.execute()


# ---------------------------------------------------------------------------
# Subscribe : générateur d'events
# ---------------------------------------------------------------------------


async def subscribe(*channels: str) -> AsyncIterator[dict[str, Any]]:
    """Abonnement à un ou plusieurs canaux. Yield des dicts {event, data}.

    À utiliser dans une coroutine SSE/WS. Boucle infinie : à terminer en
    fermant la connexion (CancelledError → finally cleanup).
    """
    client = redis.from_url(str(settings.redis_url), decode_responses=True)
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(*channels)
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
            if msg is None:
                # Keepalive logique (le caller envoie son propre ping si besoin)
                yield {"event": "_idle", "data": None}
                continue
            raw = msg.get("data")
            if not isinstance(raw, str):
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue
    except asyncio.CancelledError:
        raise
    finally:
        try:
            await pubsub.unsubscribe(*channels)
            await pubsub.close()
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass
