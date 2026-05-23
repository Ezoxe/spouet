"""Client API Spotify : contrôle de lecture avec refresh automatique.

Le refresh_token vit chiffré au coffre (scope `spotify:<user_id>`). L'access_token
(courte durée) est mis en cache dans Redis et rafraîchi à la demande.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
import redis.asyncio as redis  # type: ignore[import-untyped]
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.config import settings
from spouet.core.logging import get_logger
from spouet.secrets import store as secrets_store
from spouet.spotify import oauth

logger = get_logger(__name__)
API = "https://api.spotify.com/v1"


class SpotifyError(RuntimeError):
    """Erreur de contrôle (non connecté, pas d'appareil, pas Premium…)."""


def _scope(user_id: UUID) -> str:
    return f"spotify:{user_id}"


def _redis() -> redis.Redis:
    return redis.from_url(str(settings.redis_url), decode_responses=True)


def _track_brief(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "uri": t.get("uri"),
        "name": t.get("name"),
        "artists": ", ".join(a.get("name", "") for a in t.get("artists", [])),
        "album": (t.get("album") or {}).get("name"),
    }


async def is_connected(db: AsyncSession, user_id: UUID) -> bool:
    try:
        await secrets_store.get_value(db, scope=_scope(user_id), key="refresh_token")
        return True
    except secrets_store.SecretMissingError:
        return False


async def store_tokens(db: AsyncSession, user_id: UUID, token_resp: dict[str, Any]) -> None:
    refresh = token_resp.get("refresh_token")
    if refresh:
        await secrets_store.upsert(
            db,
            scope=_scope(user_id),
            key="refresh_token",
            value=refresh,
            description="Spotify refresh token",
        )
    await _cache_access(user_id, token_resp.get("access_token"), token_resp.get("expires_in", 3600))


async def disconnect(db: AsyncSession, user_id: UUID) -> None:
    await secrets_store.delete(db, scope=_scope(user_id), key="refresh_token")
    cli = _redis()
    try:
        await cli.delete(f"spotify_access:{user_id}")
    finally:
        await cli.aclose()


async def _cache_access(user_id: UUID, token: str | None, expires_in: Any) -> None:
    if not token:
        return
    try:
        ttl = max(30, int(expires_in) - 60)
    except (TypeError, ValueError):
        ttl = 3000
    cli = _redis()
    try:
        await cli.set(f"spotify_access:{user_id}", token, ex=ttl)
    finally:
        await cli.aclose()


async def _access_token(db: AsyncSession, user_id: UUID) -> str:
    cli = _redis()
    try:
        cached = await cli.get(f"spotify_access:{user_id}")
    finally:
        await cli.aclose()
    if cached:
        return cached
    try:
        refresh = await secrets_store.get_value(db, scope=_scope(user_id), key="refresh_token")
    except secrets_store.SecretMissingError:
        raise SpotifyError("Spotify non connecté.")
    resp = await oauth.refresh_token(refresh)
    token = resp.get("access_token")
    if not token:
        raise SpotifyError("Rafraîchissement du token Spotify échoué.")
    await _cache_access(user_id, token, resp.get("expires_in", 3600))
    return token


async def _request(
    db: AsyncSession,
    user_id: UUID,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
) -> httpx.Response:
    token = await _access_token(db, user_id)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            return await client.request(
                method, f"{API}{path}", headers=headers, params=params, json=json_body
            )
    except httpx.HTTPError as e:
        raise SpotifyError(f"Spotify injoignable: {e}") from e


def _ensure_player_ok(r: httpx.Response) -> None:
    if r.status_code in (200, 202, 204):
        return
    if r.status_code == 404:
        raise SpotifyError("Aucun appareil Spotify actif — ouvre Spotify sur un appareil.")
    if r.status_code == 403:
        raise SpotifyError("Action refusée par Spotify (compte Premium requis).")
    raise SpotifyError(f"Spotify {r.status_code}: {r.text[:160]}")


async def search_tracks(
    db: AsyncSession, user_id: UUID, query: str, limit: int = 5
) -> list[dict[str, Any]]:
    r = await _request(
        db, user_id, "GET", "/search", params={"q": query, "type": "track", "limit": limit}
    )
    if r.status_code != 200:
        raise SpotifyError(f"Recherche échouée ({r.status_code}).")
    items = (r.json().get("tracks") or {}).get("items") or []
    return [_track_brief(t) for t in items]


async def play(db: AsyncSession, user_id: UUID, *, uris: list[str] | None = None) -> None:
    body = {"uris": uris} if uris else None
    _ensure_player_ok(await _request(db, user_id, "PUT", "/me/player/play", json_body=body))


async def pause(db: AsyncSession, user_id: UUID) -> None:
    _ensure_player_ok(await _request(db, user_id, "PUT", "/me/player/pause"))


async def next_track(db: AsyncSession, user_id: UUID) -> None:
    _ensure_player_ok(await _request(db, user_id, "POST", "/me/player/next"))


async def previous_track(db: AsyncSession, user_id: UUID) -> None:
    _ensure_player_ok(await _request(db, user_id, "POST", "/me/player/previous"))


async def set_volume(db: AsyncSession, user_id: UUID, percent: int) -> None:
    percent = max(0, min(100, int(percent)))
    _ensure_player_ok(
        await _request(db, user_id, "PUT", "/me/player/volume", params={"volume_percent": percent})
    )


async def current_playback(db: AsyncSession, user_id: UUID) -> dict[str, Any] | None:
    r = await _request(db, user_id, "GET", "/me/player")
    if r.status_code == 204:
        return None
    if r.status_code != 200:
        raise SpotifyError(f"Spotify {r.status_code}.")
    data = r.json()
    item = data.get("item") or {}
    device = data.get("device") or {}
    return {
        "is_playing": bool(data.get("is_playing")),
        "track": _track_brief(item) if item else None,
        "volume": device.get("volume_percent"),
        "device": device.get("name"),
    }
