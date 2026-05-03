"""HITL approval queue (Redis).

Workflow :
  1. Orchestrator détecte un tool_call qui demande approval (network=bridge OU tool.requires_approval)
  2. Crée une "approval request" dans Redis : `approval:{request_id}` (TTL 5min)
  3. Publie un event `approval_required` sur conv:{conversation_id}
  4. UI montre un bandeau, l'utilisateur clique approve/reject
  5. POST /api/tools/approvals/{id} → set la valeur dans Redis
  6. Orchestrator (qui poll) lit la valeur, débloque ou skip l'exécution
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import redis.asyncio as redis

from spouet.core.config import settings

_TTL = 300  # 5 minutes


def _client() -> redis.Redis:
    return redis.from_url(str(settings.redis_url), decode_responses=True)


def _key(request_id: str) -> str:
    return f"approval:{request_id}"


async def request_approval(payload: dict[str, Any]) -> str:
    rid = str(uuid.uuid4())
    cli = _client()
    try:
        await cli.set(_key(rid), json.dumps({"status": "pending", "payload": payload}), ex=_TTL)
    finally:
        await cli.aclose()
    return rid


async def submit_decision(request_id: str, *, approved: bool, note: str | None = None) -> bool:
    """True si la requête existait, False si TTL expiré."""
    cli = _client()
    try:
        raw = await cli.get(_key(request_id))
        if raw is None:
            return False
        data = json.loads(raw)
        data["status"] = "approved" if approved else "rejected"
        data["note"] = note
        await cli.set(_key(request_id), json.dumps(data), ex=_TTL)
        return True
    finally:
        await cli.aclose()


async def wait_for_decision(request_id: str, *, poll_s: float = 0.5, timeout_s: float = 240) -> str:
    """Bloque jusqu'à `approved`/`rejected`. Retourne 'timeout' si TTL dépassé."""
    cli = _client()
    try:
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            raw = await cli.get(_key(request_id))
            if raw is None:
                return "timeout"
            data = json.loads(raw)
            if data["status"] in ("approved", "rejected"):
                return data["status"]
            await asyncio.sleep(poll_s)
        return "timeout"
    finally:
        await cli.aclose()
