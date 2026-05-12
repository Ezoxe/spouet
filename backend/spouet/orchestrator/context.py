"""Construction du contexte envoyé à Ollama : historique + system prompt + RAG/memory."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.logging import get_logger
from spouet.db.models import Conversation, Message

_log = get_logger(__name__)

# Heuristique : ~4 chars/token (suffisant pour décider de la troncature)
CHARS_PER_TOKEN = 4
DEFAULT_CTX_TOKENS = 8192
KEEP_RATIO = 0.7  # tronque si historique > 70 % du contexte


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


async def build_extra_system(
    db: AsyncSession, *, user_id: UUID, last_user_text: str
) -> str | None:
    """Construit les injections automatiques (RAG + memory) pour le prochain prompt."""
    parts: list[str] = []

    # Memory long-terme (pertinence par recherche vectorielle si dispo, sinon top par score)
    try:
        from spouet.memory.store import recall_relevant

        mems = await recall_relevant(db, user_id=user_id, query=last_user_text, k=5)
        if mems:
            lines = [f"- {m.key}: {m.value}" for m in mems]
            parts.append("Mémoire utilisateur :\n" + "\n".join(lines))
    except Exception as e:  # noqa: BLE001
        _log.warning("memory.recall_failed", error=str(e))

    # RAG : contexte documents
    try:
        from spouet.rag.retriever import format_for_prompt, search

        hits = await search(db, user_id=user_id, query=last_user_text, k=4)
        formatted = format_for_prompt(hits)
        if formatted:
            parts.append(formatted)
    except Exception as e:  # noqa: BLE001
        _log.warning("rag.search_failed", error=str(e))

    return "\n\n".join(parts) if parts else None


async def build_messages(
    db: AsyncSession,
    *,
    conversation: Conversation,
    extra_system: str | None = None,
    ctx_tokens: int = DEFAULT_CTX_TOKENS,
) -> list[dict[str, Any]]:
    """Construit la liste de messages OpenAI-style envoyée à `/api/chat`.

    Ordre :
      1. system prompt de la conversation (si défini) + injections RAG/memory
      2. historique tronqué (les plus récents en priorité)
    """
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at.asc())
            )
        ).scalars().all()
    )

    # Retire le placeholder assistant vide créé par chat_loop avant le stream.
    # Tel quel, llama.cpp /v1/chat/completions interprète un dernier message
    # assistant comme un prefill et refuse la combinaison avec un template
    # « thinking » (Gemma 4, Qwen3, DeepSeek-R1…) :
    #   400 « Assistant response prefill is incompatible with enable_thinking ».
    while (
        rows
        and rows[-1].role == "assistant"
        and not (rows[-1].content or "").strip()
        and not rows[-1].content_json
    ):
        rows.pop()

    # Construit le system prompt combiné
    system_parts: list[str] = []
    if conversation.system_prompt:
        system_parts.append(conversation.system_prompt.strip())
    if extra_system:
        system_parts.append(extra_system.strip())
    system_text = "\n\n".join(p for p in system_parts if p)

    out: list[dict[str, Any]] = []
    if system_text:
        out.append({"role": "system", "content": system_text})

    # Troncature glissante : on part de la fin et on remonte tant qu'on tient
    budget = int(ctx_tokens * KEEP_RATIO) - estimate_tokens(system_text)
    selected: list[Message] = []
    for msg in reversed(rows):
        cost = estimate_tokens(msg.content or "")
        if cost > budget and selected:
            break
        budget -= cost
        selected.append(msg)
    selected.reverse()

    for m in selected:
        item: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.content_json:
            # Pour les messages tool / tool_calls Ollama
            item.update(m.content_json)
        out.append(item)

    return out
