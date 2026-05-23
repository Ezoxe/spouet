"""Appels LLM one-shot pour le tri et la rédaction de réponses mail.

Réutilise le routeur de nodes (`pick_node`) + le streaming Ollama (`chat_stream`)
mais agrège la réponse complète (pas de conversation persistée).
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.logging import get_logger
from spouet.db.models import MailAccount, MailMessage, Node
from spouet.nodes.agent_client import ensure_model_loaded
from spouet.nodes.client import chat_stream
from spouet.nodes.router import pick_node

logger = get_logger(__name__)


async def complete(
    db: AsyncSession, *, model: str, system: str, user: str, max_tokens: int = 512
) -> str:
    """Un aller-retour LLM (system + user) → texte complet."""
    choice = await pick_node(db, model)
    if choice.needs_load:
        node = await db.get(Node, choice.node_id)
        if node is not None:
            try:
                async for _ev in ensure_model_loaded(node, choice.model):
                    pass
            except Exception as e:  # noqa: BLE001
                logger.warning("mail.model_load_failed", model=model, error=str(e))

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    out = ""
    async for chunk in chat_stream(
        choice.base_url,
        model=choice.model,
        messages=messages,
        options={"num_predict": max_tokens, "temperature": 0.2},
    ):
        out += (chunk.get("message") or {}).get("content") or ""
        if chunk.get("done"):
            break
    return out.strip()


def _parse_json_object(raw: str) -> dict[str, Any]:
    """Extrait le premier objet JSON d'une réponse (les LLM ajoutent du bavardage)."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


_VALID_CLASSES = {"spam", "important", "normal", "newsletter", "notification"}

CLASSIFY_SYSTEM = (
    "Tu es un assistant de tri d'emails. Analyse le mail et réponds UNIQUEMENT par un "
    "objet JSON valide, sans texte autour, avec EXACTEMENT ces clés :\n"
    '{"classification": "spam|important|normal|newsletter|notification", '
    '"importance": <entier 0-100>, "needs_reply": <bool>, '
    '"summary": "<résumé en une phrase, en français>"}\n'
    "- spam : pourriel, hameçonnage, publicité non sollicitée.\n"
    "- important : demande une action ou attention de l'utilisateur.\n"
    "- needs_reply : true seulement si une réponse personnelle est clairement attendue."
)


async def classify(
    db: AsyncSession, *, model: str, sender: str, subject: str, body: str
) -> dict[str, Any]:
    user = f"De: {sender}\nSujet: {subject}\n\nCorps:\n{(body or '')[:3000]}"
    raw = await complete(db, model=model, system=CLASSIFY_SYSTEM, user=user, max_tokens=300)
    data = _parse_json_object(raw)

    classification = str(data.get("classification") or "normal").lower().strip()
    if classification not in _VALID_CLASSES:
        classification = "normal"
    try:
        importance = max(0, min(100, int(data.get("importance", 0))))
    except (TypeError, ValueError):
        importance = 0
    return {
        "classification": classification,
        "importance": importance,
        "needs_reply": bool(data.get("needs_reply", False)),
        "summary": str(data.get("summary") or "")[:500],
    }


async def draft_reply(
    db: AsyncSession, *, model: str, account: MailAccount, message: MailMessage
) -> str:
    sig = f"\n\nTermine par cette signature :\n{account.signature}" if account.signature else ""
    system = (
        f"Tu rédiges, en français, une réponse à un email reçu sur la boîte {account.email}. "
        "Ton poli, professionnel et concis. N'invente aucune information factuelle que tu "
        "ne connais pas ; en cas de doute, propose de revenir vers l'expéditeur. Rends "
        "UNIQUEMENT le corps de la réponse, sans objet ni en-têtes." + sig
    )
    user = (
        f"Mail reçu de {message.from_name} <{message.from_addr}>\n"
        f"Sujet: {message.subject}\n\n{(message.body_text or '')[:3000]}"
    )
    return await complete(db, model=model, system=system, user=user, max_tokens=800)
