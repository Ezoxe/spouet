"""Boucle de chat : sélectionne un node, stream les tokens, gère tool_calls (function calling)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.logging import get_logger
from spouet.db.models import Conversation, Message, Tool, ToolExecution
from spouet.nodes.client import OllamaError, chat_stream
from spouet.nodes.router import NoSuitableNodeError, pick_node
from spouet.orchestrator.context import build_extra_system, build_messages
from spouet.orchestrator.persona import build_persona_prompt
from spouet.realtime.hub import conv_channel, publish
from spouet.secrets.store import SecretMissingError, resolve_env
from spouet.tools.approval import request_approval, wait_for_decision
from spouet.tools.manifest import validate_args
from spouet.tools.runner import run_tool

logger = get_logger(__name__)

MAX_TOOL_ITERATIONS = 8


async def stream_assistant_reply(
    db: AsyncSession,
    *,
    conversation: Conversation,
    user_text: str,
    model_override: str | None = None,
    enable_tools: bool = True,
) -> AsyncIterator[dict[str, Any]]:
    """Pipeline complet : insère le message user, choisit un node, stream la réponse,
    gère les tool_calls jusqu'à terminaison.
    """
    model = model_override or conversation.model_pref
    if not model:
        yield {"event": "error", "data": {"message": "No model selected"}}
        return

    user_msg = Message(conversation_id=conversation.id, role="user", content=user_text)
    db.add(user_msg)
    await db.commit()

    channel = conv_channel(conversation.id)
    await publish(channel, "message", _msg_payload(user_msg))

    tools_payload, tools_by_slug = await _load_active_tools(db) if enable_tools else (None, {})

    excluded: set[UUID] = set()
    iteration = 0
    last_user_id = user_msg.id
    last_error: str | None = None

    while iteration < MAX_TOOL_ITERATIONS:
        iteration += 1
        try:
            choice = await pick_node(db, model, exclude_node_ids=excluded)
        except NoSuitableNodeError as e:
            err_msg = last_error if last_error and excluded else str(e)
            yield {"event": "error", "data": {"message": err_msg}}
            await publish(channel, "error", {"message": err_msg})
            return

        active_tools = tools_payload if (tools_payload and choice.supports_tools) else None

        assistant_msg = Message(
            conversation_id=conversation.id,
            role="assistant",
            content="",
            parent_id=last_user_id,
            model_used=choice.model,
            node_id=choice.node_id,
        )
        db.add(assistant_msg)
        await db.commit()
        await publish(channel, "message_start", {"message_id": str(assistant_msg.id)})
        yield {"event": "node", "data": {"name": choice.name, "model": choice.model}}
        await publish(channel, "node", {"name": choice.name, "model": choice.model})

        # M4 : persona Spouet + RAG + memory au premier tour uniquement
        extra_system = None
        if iteration == 1:
            persona = await build_persona_prompt(
                db,
                node_name=choice.name,
                model_name=choice.model,
                user_id=conversation.user_id,
            )
            extras = await build_extra_system(
                db, user_id=conversation.user_id, last_user_text=user_text
            )
            extra_system = persona if not extras else f"{persona}\n\n{extras}"
        messages = await build_messages(
            db, conversation=conversation, extra_system=extra_system
        )
        accumulated = ""
        tokens_out = 0
        tool_calls_out: list[dict[str, Any]] = []
        started = time.monotonic()
        try:
            async for chunk in chat_stream(
                choice.base_url,
                model=choice.model,
                messages=messages,
                tools=active_tools,
            ):
                msg = chunk.get("message") or {}
                token_text = msg.get("content") or ""
                if token_text:
                    accumulated += token_text
                    tokens_out += 1
                    assistant_msg.content = accumulated
                    yield {"event": "token", "data": {"text": token_text}}
                    await publish(
                        channel, "token", {"message_id": str(assistant_msg.id), "text": token_text}
                    )

                tcs = msg.get("tool_calls")
                if tcs:
                    tool_calls_out.extend(tcs)

                if chunk.get("done"):
                    assistant_msg.tokens_in = chunk.get("prompt_eval_count")
                    assistant_msg.tokens_out = chunk.get("eval_count") or tokens_out
                    assistant_msg.finish_reason = chunk.get("done_reason") or "stop"
                    break
            assistant_msg.latency_ms = int((time.monotonic() - started) * 1000)
            if tool_calls_out:
                assistant_msg.content_json = {"tool_calls": tool_calls_out}
            await db.commit()

        except OllamaError as e:
            logger.warning("chat.node_error", node=choice.name, error=str(e))
            excluded.add(choice.node_id)
            last_error = str(e)
            await publish(channel, "node_error", {"node": choice.name, "error": str(e)})
            continue  # failover

        # Pas de tool_calls → fin de la conversation
        if not tool_calls_out:
            done = {
                "message_id": str(assistant_msg.id),
                "tokens_out": assistant_msg.tokens_out,
                "latency_ms": assistant_msg.latency_ms,
            }
            yield {"event": "done", "data": done}
            await publish(channel, "done", done)
            return

        # Exécuter chaque tool_call et insérer un message role=tool en réponse
        for tc in tool_calls_out:
            yield {"event": "tool_calls", "data": tc}
            await publish(channel, "tool_call", tc)
            tool_msg = await _execute_tool_call(
                db,
                conversation=conversation,
                tool_call=tc,
                tools_by_slug=tools_by_slug,
                channel=channel,
            )
            if tool_msg is not None:
                yield {
                    "event": "tool_result",
                    "data": {"message_id": str(tool_msg.id), "content": tool_msg.content},
                }
                last_user_id = tool_msg.id

    # Garde-fou : trop d'itérations tools
    yield {"event": "error", "data": {"message": "max tool iterations reached"}}
    await publish(channel, "error", {"message": "max tool iterations reached"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_active_tools(
    db: AsyncSession,
) -> tuple[list[dict[str, Any]] | None, dict[str, Tool]]:
    rows = (await db.execute(select(Tool).where(Tool.enabled.is_(True)))).scalars().all()
    if not rows:
        return None, {}
    payload = [
        {
            "type": "function",
            "function": {
                "name": t.slug,
                "description": t.description or t.name,
                "parameters": t.manifest_json.get("input_schema", {"type": "object"}),
            },
        }
        for t in rows
    ]
    return payload, {t.slug: t for t in rows}


async def _execute_tool_call(
    db: AsyncSession,
    *,
    conversation: Conversation,
    tool_call: dict[str, Any],
    tools_by_slug: dict[str, Tool],
    channel: str,
) -> Message | None:
    fn = tool_call.get("function") or {}
    slug = fn.get("name")
    raw_args = fn.get("arguments") or {}
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except json.JSONDecodeError:
            raw_args = {}

    tool = tools_by_slug.get(slug or "")
    if tool is None:
        return await _persist_tool_message(
            db, conversation, slug or "?", {"error": f"unknown tool '{slug}'"}
        )

    schema = tool.manifest_json.get("input_schema", {"type": "object"})
    errs = validate_args(schema, raw_args)
    if errs:
        result = {"error": "invalid arguments", "details": errs}
        return await _persist_tool_message(db, conversation, tool.slug, result)

    # HITL approval si requis
    if tool.requires_approval:
        rid = await request_approval(
            {
                "tool_slug": tool.slug,
                "args": raw_args,
                "conversation_id": str(conversation.id),
                "tool_image": tool.image,
                "network": tool.network_mode,
            }
        )
        await publish(
            channel,
            "approval_required",
            {"request_id": rid, "tool": tool.slug, "args": raw_args},
        )
        decision = await wait_for_decision(rid)
        if decision != "approved":
            result = {"error": f"approval {decision}"}
            return await _persist_tool_message(db, conversation, tool.slug, result)

    # Résolution des secrets déclarés dans le manifest + env statique
    secrets_map = tool.manifest_json.get("secrets") or {}
    static_env = {
        str(k): str(v) for k, v in (tool.manifest_json.get("env") or {}).items()
    }
    try:
        env_vars: dict[str, str] = (
            await resolve_env(db, secrets_map, fallback_scope=f"tool:{tool.slug}")
            if secrets_map
            else {}
        )
    except SecretMissingError as e:
        return await _persist_tool_message(
            db, conversation, tool.slug, {"error": str(e)}
        )
    env_vars.update(static_env)

    # Exécute le conteneur
    exec_row = ToolExecution(
        tool_id=tool.id,
        args_json=raw_args,
        status="running",
        started_at=datetime.now(UTC),
    )
    db.add(exec_row)
    await db.commit()

    res = await run_tool(
        image=tool.image,
        args=raw_args,
        network=tool.network_mode,
        timeout_s=tool.timeout_s,
        mem_limit=tool.manifest_json.get("mem_limit", "256m"),
        cpu_limit=float(tool.manifest_json.get("cpu_limit", 1.0)),
        env=env_vars,
    )

    exec_row.status = res.status
    exec_row.stdout = res.stdout
    exec_row.stderr = res.stderr
    exec_row.exit_code = res.exit_code
    exec_row.duration_ms = res.duration_ms
    exec_row.container_id = res.container_id
    exec_row.finished_at = datetime.now(UTC)
    await db.commit()

    await publish(
        channel,
        "tool_result",
        {
            "tool": tool.slug,
            "status": res.status,
            "duration_ms": res.duration_ms,
            "exit_code": res.exit_code,
        },
    )

    payload: dict[str, Any] = (
        res.parsed if res.parsed is not None else {"raw_stdout": res.stdout, "stderr": res.stderr}
    )
    return await _persist_tool_message(db, conversation, tool.slug, payload)


async def _persist_tool_message(
    db: AsyncSession, conversation: Conversation, tool_name: str, content: dict[str, Any]
) -> Message:
    text = json.dumps(content, ensure_ascii=False)
    msg = Message(
        conversation_id=conversation.id,
        role="tool",
        content=text,
        content_json={"tool_name": tool_name},
    )
    db.add(msg)
    await db.commit()
    await publish(conv_channel(conversation.id), "message", _msg_payload(msg))
    return msg


def _msg_payload(m: Message) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "role": m.role,
        "content": m.content,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
