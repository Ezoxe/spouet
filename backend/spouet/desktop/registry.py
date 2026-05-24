"""Registre éphémère des capacités du client desktop connecté.

Le client Tauri POST ``/api/desktop/hello`` périodiquement avec ses capacités
(écrans, applications détectées, version, OS). On les stocke en Redis avec un
TTL court : si le client se déconnecte, la clé expire et l'IA sait qu'elle ne
peut plus piloter le PC. Consommé par la persona (capability-aware) et par les
gates de sécurité du pont desktop.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import redis.asyncio as redis

from spouet.core.config import settings

# Le client rafraîchit ~toutes les 60 s ; 150 s laisse une marge avant expiration.
_TTL = 150


def _client() -> redis.Redis:
    return redis.from_url(str(settings.redis_url), decode_responses=True)


def _key(user_id: UUID | str) -> str:
    return f"desktop:caps:{user_id}"


async def set_caps(user_id: UUID | str, caps: dict[str, Any]) -> None:
    cli = _client()
    try:
        await cli.set(_key(user_id), json.dumps(caps, ensure_ascii=False, default=str), ex=_TTL)
    finally:
        await cli.aclose()


async def get_caps(user_id: UUID | str) -> dict[str, Any] | None:
    cli = _client()
    try:
        raw = await cli.get(_key(user_id))
    finally:
        await cli.aclose()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


async def is_connected(user_id: UUID | str) -> bool:
    return (await get_caps(user_id)) is not None


def known_app_names(caps: dict[str, Any] | None) -> list[str]:
    """Liste des noms d'applications détectées sur le client (pour le gating)."""
    if not caps:
        return []
    apps = caps.get("apps") or []
    names: list[str] = []
    for a in apps:
        if isinstance(a, str):
            names.append(a)
        elif isinstance(a, dict) and isinstance(a.get("name"), str):
            names.append(a["name"])
    return names
