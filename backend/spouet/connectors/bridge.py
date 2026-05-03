"""Bridge entre les events inbound d'un connector et l'orchestrateur Spouet.

Quand un connector POST un message via WS, le bridge :

1. trouve (ou crée) la route ``(connector_id, external_id)`` → conversation
2. lance l'orchestrateur sur cette conversation avec le texte reçu
3. agrège les tokens de réponse (pas de stream vers le service externe : on
   limite la pression API et la mauvaise UX type "tokens qui clignotent")
4. publie une commande outbound ``send_message`` vers le connector

Le bridge tourne dans une tâche dédiée pour ne pas bloquer la WS du connector.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.logging import get_logger
from spouet.db import async_session_factory
from spouet.db.models import Connector, ConnectorRoute, Conversation
from spouet.orchestrator.chat_loop import stream_assistant_reply
from spouet.realtime.hub import connector_outbound_channel, publish

logger = get_logger(__name__)

DEFAULT_BOT_PERSONA = "Tu es l'assistant Spouet relayé via un connector externe."


async def _get_or_create_route(
    db: AsyncSession,
    connector: Connector,
    *,
    external_id: str,
    external_label: str,
    metadata: dict[str, Any],
) -> ConnectorRoute:
    route = await db.scalar(
        select(ConnectorRoute).where(
            ConnectorRoute.connector_id == connector.id,
            ConnectorRoute.external_id == external_id,
        )
    )
    if route is not None:
        return route

    config = connector.config_json or {}
    persona = (config.get("bot_persona") or DEFAULT_BOT_PERSONA).strip()
    model_pref = config.get("default_model")

    conv = Conversation(
        user_id=connector.user_id,
        title=f"[{connector.slug}] {external_label}"[:255],
        system_prompt=persona,
        model_pref=model_pref,
    )
    db.add(conv)
    await db.flush()

    route = ConnectorRoute(
        connector_id=connector.id,
        external_id=external_id,
        conversation_id=conv.id,
        metadata_json=metadata,
    )
    db.add(route)
    await db.commit()
    await db.refresh(route)
    logger.info(
        "connector.route_created",
        connector=connector.slug,
        external_id=external_id,
        conv=str(conv.id),
    )
    return route


async def _run_orchestrator(
    connector_id: str, external_id: str, text: str, reply_to: str | None
) -> None:
    """Tâche détachée : lance le chat loop puis publie la réponse outbound."""
    async with async_session_factory()() as db:
        connector = await db.get(Connector, connector_id)
        if connector is None or not connector.enabled:
            return
        route = await db.scalar(
            select(ConnectorRoute).where(
                ConnectorRoute.connector_id == connector.id,
                ConnectorRoute.external_id == external_id,
            )
        )
        if route is None:
            logger.warning(
                "connector.route_missing", connector=connector.slug, external=external_id
            )
            return
        conv = await db.get(Conversation, route.conversation_id)
        if conv is None:
            return

        # Indique "en train d'écrire" au service externe
        await publish(
            connector_outbound_channel(connector.id),
            "typing",
            {"external_id": external_id},
        )

        accumulated = ""
        had_error = False
        try:
            async for ev in stream_assistant_reply(
                db, conversation=conv, user_text=text
            ):
                if ev["event"] == "token":
                    accumulated += (ev["data"] or {}).get("text", "")
                elif ev["event"] == "error":
                    had_error = True
                    accumulated += f"\n\n⚠️ {(ev['data'] or {}).get('message', 'erreur')}"
                elif ev["event"] == "done":
                    break
        except Exception as e:  # noqa: BLE001
            logger.exception("connector.bridge_failed", error=str(e))
            accumulated = "⚠️ Erreur backend Spouet."
            had_error = True

        final = accumulated.strip() or ("(pas de réponse)" if not had_error else "(erreur)")

        await publish(
            connector_outbound_channel(connector.id),
            "send_message",
            {
                "external_id": external_id,
                "content": final,
                "reply_to": reply_to,
            },
        )


async def handle_inbound_event(
    db: AsyncSession,
    connector: Connector,
    *,
    kind: str,
    payload: dict[str, Any],
) -> None:
    """Point d'entrée invoqué par la WS connector pour chaque event reçu."""
    if kind == "ping":
        return

    if kind != "message":
        logger.warning(
            "connector.unsupported_kind", connector=connector.slug, kind=kind
        )
        return

    external_id = str(payload.get("external_id") or "").strip()
    text = str(payload.get("content") or "").strip()
    if not external_id or not text:
        return

    external_label = str(payload.get("external_label") or external_id)
    metadata = dict(payload.get("metadata") or {})
    reply_to = payload.get("reply_to")

    await _get_or_create_route(
        db,
        connector,
        external_id=external_id,
        external_label=external_label,
        metadata=metadata,
    )

    asyncio.create_task(
        _run_orchestrator(
            connector_id=str(connector.id),
            external_id=external_id,
            text=text,
            reply_to=str(reply_to) if reply_to else None,
        )
    )
