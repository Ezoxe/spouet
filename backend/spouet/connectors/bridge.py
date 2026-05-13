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
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.logging import get_logger
from spouet.db import async_session_factory
from spouet.db.models import Connector, ConnectorRoute, Conversation
from spouet.orchestrator.chat_loop import stream_assistant_reply
from spouet.realtime.hub import connector_outbound_channel, publish

logger = get_logger(__name__)

DEFAULT_BOT_PERSONA = "Tu es l'assistant Spouet relayé via un connector externe."

# Garde des références fortes sur les tâches détachées pour éviter le GC
# (`asyncio.create_task` ne suffit pas : sans réf, l'event loop peut nettoyer
# la tâche avant sa fin et perdre l'exception).
_background_tasks: set[asyncio.Task[Any]] = set()


def _spawn_supervised(coro, *, label: str) -> asyncio.Task[Any]:
    """Lance `coro` en tâche détachée + log toute exception en done_callback.

    Remplace `asyncio.create_task(coro)` qui silenciait les erreurs.
    """
    task = asyncio.create_task(coro, name=label)
    _background_tasks.add(task)

    def _on_done(t: asyncio.Task[Any]) -> None:
        _background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.exception(
                "bridge.background_task_failed",
                task=label,
                error=str(exc),
            )

    task.add_done_callback(_on_done)
    return task


async def _get_or_create_route(
    db: AsyncSession,
    connector: Connector,
    *,
    external_id: str,
    external_label: str,
    metadata: dict[str, Any],
) -> ConnectorRoute:
    """Trouve ou crée la route (connector_id, external_id) → conversation.

    Utilise INSERT … ON CONFLICT DO NOTHING pour éviter la race SELECT+INSERT
    classique : deux messages Discord arrivant simultanément sur le même
    channel créaient potentiellement deux conversations.
    """
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

    # Connector Discord : on active automatiquement les 5 tools `spouet-*`
    # pour que l'IA puisse répondre avec des stats nodes, envoyer des embeds, etc.
    allowed_tools: list[str] = []
    if connector.slug == "discord-bot":
        allowed_tools = list(SPOUET_DISCORD_TOOLS)

    conv = Conversation(
        user_id=connector.user_id,
        title=f"[{connector.slug}] {external_label}"[:255],
        system_prompt=persona,
        model_pref=model_pref,
        allowed_tool_slugs=allowed_tools,
    )
    db.add(conv)
    await db.flush()

    # INSERT … ON CONFLICT DO NOTHING : si une autre coroutine a déjà créé
    # la route entre notre SELECT et ce moment, on ne lève pas IntegrityError.
    stmt = (
        pg_insert(ConnectorRoute)
        .values(
            connector_id=connector.id,
            external_id=external_id,
            conversation_id=conv.id,
            metadata_json=metadata,
        )
        .on_conflict_do_nothing(constraint="uq_route_connector_external")
        .returning(ConnectorRoute.id)
    )
    result = await db.execute(stmt)
    inserted_id = result.scalar_one_or_none()

    if inserted_id is None:
        # Une concurrente a gagné : on lit sa route et on rollback la conv orpheline.
        await db.delete(conv)
        await db.commit()
        existing = await db.scalar(
            select(ConnectorRoute).where(
                ConnectorRoute.connector_id == connector.id,
                ConnectorRoute.external_id == external_id,
            )
        )
        assert existing is not None  # unique constraint nous garantit qu'elle existe
        return existing

    await db.commit()
    route = await db.scalar(
        select(ConnectorRoute).where(ConnectorRoute.id == inserted_id)
    )
    assert route is not None
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


SPOUET_DISCORD_TOOLS = [
    "spouet-nodes-status",
    "spouet-node-metrics",
    "spouet-models-list",
    "spouet-discord-embed",
    "spouet-discord-react",
]


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

    if kind == "bot_info":
        # Le connector se présente : on stocke client_id pour générer l'URL OAuth
        # d'invitation côté admin.
        meta = dict(connector.metadata_json or {})
        if "client_id" in payload:
            meta["bot_user_id"] = str(payload["client_id"])
        if "username" in payload:
            meta["bot_username"] = str(payload["username"])
        connector.metadata_json = meta
        await db.commit()
        logger.info("connector.bot_info", slug=connector.slug, meta=meta)
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

    _spawn_supervised(
        _run_orchestrator(
            connector_id=str(connector.id),
            external_id=external_id,
            text=text,
            reply_to=str(reply_to) if reply_to else None,
        ),
        label=f"bridge:{connector.slug}:{external_id}",
    )
