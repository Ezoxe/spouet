"""Boucle de chat : sélectionne un node, stream les tokens, gère tool_calls (function calling)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.logging import get_logger
from spouet.db.models import Conversation, Message, Node, Tool, ToolExecution
from spouet.nodes.agent_client import (
    AgentUnreachableError,
    ModelLoadTimeoutError,
    ModelNotAvailableError,
    ensure_model_loaded,
)
from spouet.nodes.client import OllamaError, chat_stream
from spouet.nodes.router import NoSuitableNodeError, pick_node
from spouet.desktop import registry as desktop_registry
from spouet.orchestrator import builtin_tools
from spouet.orchestrator.context import build_extra_system, build_messages
from spouet.orchestrator.persona import build_persona_prompt
from spouet.realtime.hub import conv_channel, publish, workspace_channel
from spouet.secrets.store import SecretMissingError, resolve_env
from spouet.tools.approval import request_approval, wait_for_decision
from spouet.tools.manifest import validate_args
from spouet.tools.runner import run_tool

logger = get_logger(__name__)

MAX_TOOL_ITERATIONS = 8
DELEGATE_TOOL_SLUG = "delegate_to_node"
# Temps max d'attente d'une décision admin pour un tool requires_approval.
# Au-delà, on marque l'exécution comme `expired` et on continue.
TOOL_APPROVAL_TIMEOUT_S = 300

_DELEGATE_TOOL_DEF: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": DELEGATE_TOOL_SLUG,
        "description": (
            "Délègue une sous-tâche à un agent worker du workspace. "
            "Retourne le résultat complet produit par le worker."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "worker_conversation_id": {
                    "type": "string",
                    "description": "UUID de la conversation worker cible (fourni dans le system prompt)",
                },
                "prompt": {
                    "type": "string",
                    "description": "Description détaillée de la tâche à confier au worker",
                },
            },
            "required": ["worker_conversation_id", "prompt"],
        },
    },
}


async def stream_assistant_reply(
    db: AsyncSession,
    *,
    conversation: Conversation,
    user_text: str,
    model_override: str | None = None,
    enable_tools: bool = True,
    skip_user_insert: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Pipeline complet : insère le message user, choisit un node, stream la réponse,
    gère les tool_calls jusqu'à terminaison.

    `skip_user_insert=True` : ne crée pas de message user (utilisé par regenerate
    et edit&resend où le message user est déjà en base).
    """
    model = model_override or conversation.model_pref
    if not model:
        yield {"event": "error", "data": {"message": "No model selected"}}
        return

    channel = conv_channel(conversation.id)
    if skip_user_insert:
        # Récupère le dernier message user existant pour caler last_user_id
        last_user_row = (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conversation.id, Message.role == "user"
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last_user_row is None:
            yield {"event": "error", "data": {"message": "No user message to reply to"}}
            return
        user_msg = last_user_row
    else:
        user_msg = Message(
            conversation_id=conversation.id, role="user", content=user_text
        )
        db.add(user_msg)
        await db.commit()
        await publish(channel, "message", _msg_payload(user_msg))

    tools_payload, tools_by_slug = (
        await _load_active_tools(db, conversation=conversation)
        if enable_tools
        else (None, {})
    )

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

        # Cold-start : si le modèle n'est pas encore chargé sur le node retenu,
        # demande à l'agent de le charger et attend la fin avant de stream.
        if choice.needs_load:
            node_row = await db.get(Node, choice.node_id)
            if node_row is not None:
                try:
                    async for ev in ensure_model_loaded(node_row, choice.model):
                        yield ev
                        await publish(channel, ev["event"], ev["data"])
                except ModelNotAvailableError as e:
                    logger.warning("chat.model_missing", node=choice.name, error=str(e))
                    excluded.add(choice.node_id)
                    last_error = str(e)
                    await publish(channel, "node_error", {"node": choice.name, "error": str(e)})
                    continue
                except (AgentUnreachableError, ModelLoadTimeoutError) as e:
                    logger.warning("chat.load_failed", node=choice.name, error=str(e))
                    excluded.add(choice.node_id)
                    last_error = f"{choice.name}: {e}"
                    await publish(channel, "node_error", {"node": choice.name, "error": str(e)})
                    continue

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

            # Workspace manager : injecter la liste des workers
            if conversation.workspace_role == "manager" and conversation.workspace_id is not None:
                wctx = await _build_workspace_manager_context(db, conversation)
                if wctx:
                    extra_system = f"{extra_system}\n\n{wctx}" if extra_system else wctx
        messages = await build_messages(
            db, conversation=conversation, extra_system=extra_system, ctx_tokens=choice.n_ctx
        )
        accumulated = ""
        tokens_out = 0
        tool_calls_out: list[dict[str, Any]] = []
        started = time.monotonic()
        first_token_at: float | None = None
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
                    if first_token_at is None:
                        first_token_at = time.monotonic()
                        assistant_msg.ttft_ms = int((first_token_at - started) * 1000)
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
                    # llama-server émet d'abord le chunk `finish_reason`, puis —
                    # grâce à stream_options.include_usage — un dernier chunk ne
                    # portant que `usage`. On capture les compteurs au fil de l'eau
                    # SANS `break`, sinon ce chunk final (et donc prompt_eval_count)
                    # serait perdu. Le flux se clôt de lui-même sur `[DONE]`.
                    # `eval_count`/`prompt_eval_count` peuvent valoir 0 : on teste
                    # `is not None` pour ne pas écraser une valeur serveur légitime.
                    if chunk.get("prompt_eval_count") is not None:
                        assistant_msg.tokens_in = chunk.get("prompt_eval_count")
                    if chunk.get("eval_count") is not None:
                        assistant_msg.tokens_out = chunk.get("eval_count")
                    if chunk.get("done_reason"):
                        assistant_msg.finish_reason = chunk.get("done_reason")
            # Flux épuisé. Fallbacks si le serveur n'a pas fourni les compteurs
            # (option include_usage non supportée) ou le finish_reason.
            if assistant_msg.tokens_out is None:
                assistant_msg.tokens_out = tokens_out
            if assistant_msg.finish_reason is None:
                assistant_msg.finish_reason = "stop"
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

        except asyncio.CancelledError:
            # Client déconnecté (bouton « stop generation » côté UI). On persiste
            # le contenu reçu jusque-là pour ne pas le perdre, puis on propage
            # l'annulation. `asyncio.shield` garantit que le commit s'exécute
            # même si la tâche est en cours d'annulation.
            assistant_msg.content = accumulated
            assistant_msg.latency_ms = int((time.monotonic() - started) * 1000)
            assistant_msg.finish_reason = "cancelled"
            if tool_calls_out:
                assistant_msg.content_json = {"tool_calls": tool_calls_out}
            try:
                await asyncio.shield(db.commit())
            except Exception:  # noqa: BLE001
                pass
            raise

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
            fn_name = (tc.get("function") or {}).get("name")
            if builtin_tools.is_builtin(fn_name):
                # Built-in (in-process) : web_search, show_visual, macros desktop.
                outcome = await builtin_tools.execute(
                    db, conversation=conversation, tool_call=tc, channel=channel
                )
                for ev in outcome.events:
                    yield ev
                tool_msg = await _persist_tool_message(
                    db, conversation, outcome.tool_name, outcome.content
                )
            else:
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
    *,
    conversation: Conversation | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Tool]]:
    rows = (await db.execute(select(Tool).where(Tool.enabled.is_(True)))).scalars().all()

    # Restriction per-conversation : allowed_tool_slugs non vide → whitelist.
    # Sémantique uniforme : workers ET conversations classiques. Liste vide =
    # tous les tools activés globalement (comportement par défaut).
    if conversation is not None and conversation.allowed_tool_slugs:
        rows = [t for t in rows if t.slug in conversation.allowed_tool_slugs]

    payload: list[dict[str, Any]] = [
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

    # Manager → ajouter delegate_to_node
    if conversation is not None and conversation.workspace_role == "manager":
        payload.append(_DELEGATE_TOOL_DEF)

    # Built-in tools (web_search, show_visual, macros desktop…) — exécutés
    # en-process, pas en Docker. Capability-aware : les tools de pilotage PC ne
    # sont exposés que si un client desktop (app Tauri) est connecté.
    desktop_connected = False
    if conversation is not None:
        desktop_connected = await desktop_registry.is_connected(conversation.user_id)
    payload.extend(builtin_tools.tool_defs(desktop_connected=desktop_connected))

    return (payload if payload else None), {t.slug: t for t in rows}


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

    # Built-in workspace delegation
    if slug == DELEGATE_TOOL_SLUG:
        return await _execute_delegate(
            db,
            conversation=conversation,
            args=raw_args,
            channel=channel,
        )

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
        try:
            decision = await asyncio.wait_for(
                wait_for_decision(rid), timeout=TOOL_APPROVAL_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            await publish(
                channel,
                "approval_expired",
                {"request_id": rid, "tool": tool.slug},
            )
            return await _persist_tool_message(
                db,
                conversation,
                tool.slug,
                {"error": f"approval timeout après {TOOL_APPROVAL_TIMEOUT_S}s"},
            )
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


async def _build_workspace_manager_context(
    db: AsyncSession, conversation: Conversation
) -> str | None:
    """Construit le contexte injecté dans le system prompt du manager."""
    workers = (
        await db.execute(
            select(Conversation).where(
                Conversation.workspace_id == conversation.workspace_id,
                Conversation.workspace_role == "worker",
            )
        )
    ).scalars().all()

    if not workers:
        return None

    lines = [
        "Tu es le manager d'un espace de travail multi-agents. "
        "Tu peux déléguer des sous-tâches aux agents workers via l'outil `delegate_to_node`. "
        "Chaque délégation retourne le résultat complet du worker dans un message role=tool.\n",
        "Agents workers disponibles :",
    ]
    for w in workers:
        lines.append(
            f"  - « {w.title} » (modèle : {w.model_pref or '?'}) "
            f"[worker_conversation_id: {w.id}]"
        )
    return "\n".join(lines)


async def _execute_delegate(
    db: AsyncSession,
    *,
    conversation: Conversation,
    args: dict[str, Any],
    channel: str,
) -> Message:
    """Exécute une délégation vers un agent worker du même workspace."""
    worker_conv_id_raw = args.get("worker_conversation_id", "")
    prompt = args.get("prompt", "")

    if not worker_conv_id_raw or not prompt:
        return await _persist_tool_message(
            db,
            conversation,
            DELEGATE_TOOL_SLUG,
            {"error": "worker_conversation_id and prompt are required"},
        )

    try:
        wid = UUID(str(worker_conv_id_raw))
    except ValueError:
        return await _persist_tool_message(
            db,
            conversation,
            DELEGATE_TOOL_SLUG,
            {"error": f"invalid worker_conversation_id: {worker_conv_id_raw}"},
        )

    if conversation.workspace_id is None:
        return await _persist_tool_message(
            db,
            conversation,
            DELEGATE_TOOL_SLUG,
            {"error": "delegate_to_node requires a workspace context"},
        )

    worker_conv = await db.get(Conversation, wid)
    if worker_conv is None or worker_conv.workspace_id != conversation.workspace_id:
        return await _persist_tool_message(
            db,
            conversation,
            DELEGATE_TOOL_SLUG,
            {"error": "worker conversation not found or not in same workspace"},
        )

    ws_channel = workspace_channel(conversation.workspace_id)
    await publish(
        ws_channel,
        "worker_start",
        {"conv_id": str(worker_conv.id), "title": worker_conv.title},
    )

    result_text = ""
    async for ev in stream_assistant_reply(
        db,
        conversation=worker_conv,
        user_text=prompt,
        enable_tools=bool(worker_conv.allowed_tool_slugs),
    ):
        evt = ev["event"]
        if evt == "token":
            t = ev["data"]["text"]
            result_text += t
            await publish(
                ws_channel,
                "worker_token",
                {"conv_id": str(worker_conv.id), "text": t},
            )
        elif evt == "done":
            await publish(
                ws_channel,
                "worker_done",
                {
                    "conv_id": str(worker_conv.id),
                    "tokens_out": ev["data"].get("tokens_out"),
                },
            )
        elif evt == "error":
            await publish(
                ws_channel,
                "worker_error",
                {
                    "conv_id": str(worker_conv.id),
                    "message": ev["data"].get("message", ""),
                },
            )

    return await _persist_tool_message(
        db,
        conversation,
        DELEGATE_TOOL_SLUG,
        {
            "worker_conversation_id": str(worker_conv.id),
            "worker_title": worker_conv.title,
            "result": result_text,
        },
    )
