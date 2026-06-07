"""Génération automatique du titre + tags d'une conversation (best-effort).

Appelé après les premiers échanges (endpoint `/conversations/{id}/autoname`).
Tente un petit appel LLM non-streaming pour produire un JSON {title, tags} ; en
cas d'échec (modèle minuscule au JSON invalide, node indisponible, modèle non
chargé) on retombe sur un titre dérivé du premier message utilisateur. Jamais
bloquant pour le chat : toute exception est avalée par l'appelant.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.config import settings
from spouet.core.logging import get_logger
from spouet.db.models import Conversation, Message
from spouet.nodes.client import LlamaError, chat_stream
from spouet.nodes.router import NoSuitableNodeError, pick_node

logger = get_logger(__name__)

# Titres considérés comme « pas encore nommés » → on autorise la surcharge auto.
DEFAULT_TITLES = {"", "…", "new conversation", "nouvelle conversation", "[compagnon]"}
MAX_TAGS = 6
_PROMPT_MESSAGES = 6  # nb de messages user/assistant pris en compte (contexte court)
_MAX_MSG_CHARS = 350

_SYS_PROMPT = (
    "Tu génères des métadonnées concises pour une conversation. Réponds "
    "UNIQUEMENT par un objet JSON valide, sans aucun texte autour, au format "
    'exact : {"title": "<titre de 3 à 6 mots, en français, sans guillemets>", '
    '"tags": ["<2 à 4 mots-clés en minuscules>"]}. Le titre résume le sujet '
    "principal ; les tags sont des thèmes courts (un ou deux mots chacun)."
)


def _is_default_title(title: str) -> bool:
    return (title or "").strip().lower() in DEFAULT_TITLES


def _fallback_title(first_user: str) -> str:
    t = re.sub(r"\s+", " ", (first_user or "").strip())
    if not t:
        return "Conversation"
    short = " ".join(t.split(" ")[:8])
    return short[:60].strip() or "Conversation"


def _clean_title(raw: str) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip()).strip(" \"'«»`")[:60].strip()


def _clean_tags(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        s = re.sub(r"\s+", " ", str(item or "").strip().lower()).strip("#").strip()[:24].strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= MAX_TAGS:
            break
    return out


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def _transcript(db: AsyncSession, conversation: Conversation) -> tuple[str, str]:
    rows = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.role.in_(("user", "assistant")),
            )
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()
    first_user = next((m.content for m in rows if m.role == "user" and m.content), "")
    parts: list[str] = []
    for m in rows[:_PROMPT_MESSAGES]:
        content = (m.content or "").strip()
        if not content:
            continue
        who = "Utilisateur" if m.role == "user" else "Assistant"
        parts.append(f"{who}: {content[:_MAX_MSG_CHARS]}")
    return first_user, "\n".join(parts)


async def _complete(base_url: str, model: str, transcript: str) -> str:
    messages = [
        {"role": "system", "content": _SYS_PROMPT},
        {"role": "user", "content": f"Conversation :\n{transcript}\n\nRéponds en JSON."},
    ]
    content = ""
    async for chunk in chat_stream(
        base_url,
        model=model,
        messages=messages,
        options={"num_predict": 160, "temperature": 0.2},
    ):
        content += (chunk.get("message") or {}).get("content") or ""
    return content


async def _llm_meta(db: AsyncSession, conversation: Conversation, transcript: str) -> dict:
    if not settings.chat_autoname_enabled:
        return {}
    # Modèle dédié (petit) si configuré, sinon le modèle de la conversation.
    model = settings.chat_autoname_model or conversation.model_pref
    if not model:
        return {}
    try:
        choice = await pick_node(db, model)
    except NoSuitableNodeError:
        return {}
    # On n'utilise le modèle que s'il est déjà chaud : pas de cold-load (qui, sur
    # un llama-server mono-modèle, éjecterait le modèle de chat). Le modèle dédié
    # de nommage doit donc rester chargé sur sa propre node / instance.
    if choice.needs_load:
        return {}
    try:
        raw = await _complete(choice.base_url, choice.model, transcript)
    except LlamaError as e:
        logger.info("autoname.llm_failed", error=str(e))
        return {}
    return _extract_json(raw)


async def autoname_conversation(db: AsyncSession, conversation: Conversation) -> bool:
    """Met à jour le titre (si encore par défaut) + fusionne les tags.

    Retourne True si la conversation a été modifiée.
    """
    first_user, transcript = await _transcript(db, conversation)
    if not transcript:
        return False

    meta = await _llm_meta(db, conversation, transcript)
    changed = False

    if _is_default_title(conversation.title):
        title = _clean_title(str(meta.get("title", ""))) or _fallback_title(first_user)
        if title and title != conversation.title:
            conversation.title = title
            changed = True

    new_tags = _clean_tags(meta.get("tags"))
    if new_tags:
        merged = list(conversation.tags or [])
        for t in new_tags:
            if t not in merged:
                merged.append(t)
        merged = merged[:MAX_TAGS]
        if merged != list(conversation.tags or []):
            conversation.tags = merged
            changed = True

    if changed:
        await db.commit()
    return changed
