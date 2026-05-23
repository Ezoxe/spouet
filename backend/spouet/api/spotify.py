"""Routes Spotify : OAuth (login/callback) + statut + contrôle de lecture.

`/control` est l'endpoint pivot : il sert l'UI ET le tool `spotify` (réseau
`internal`) que l'IA appelle pour lancer/piloter la musique.
"""

from __future__ import annotations

import uuid as uuidlib
from uuid import UUID

import redis.asyncio as redis  # type: ignore[import-untyped]
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from spouet.api.deps import CurrentUser, DbSession
from spouet.core.config import settings
from spouet.core.logging import get_logger
from spouet.spotify import client, oauth

router = APIRouter()
logger = get_logger(__name__)

_STATE_TTL = 600


def _redis() -> redis.Redis:
    return redis.from_url(str(settings.redis_url), decode_responses=True)


class ControlIn(BaseModel):
    action: str
    query: str | None = None
    volume: int | None = None


@router.get("/login")
async def login(user: CurrentUser) -> dict:
    if not oauth.is_configured():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Spotify non configuré : renseigne SPOUET_SPOTIFY_CLIENT_ID / "
            "SPOUET_SPOTIFY_CLIENT_SECRET / SPOUET_SPOTIFY_REDIRECT_URI.",
        )
    state = uuidlib.uuid4().hex
    cli = _redis()
    try:
        await cli.set(f"spotify_oauth:{state}", str(user.id), ex=_STATE_TTL)
    finally:
        await cli.aclose()
    return {"url": oauth.authorize_url(state)}


@router.get("/callback")
async def callback(
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    def _page(msg: str, ok: bool = True) -> HTMLResponse:
        color = "#16a34a" if ok else "#dc2626"
        return HTMLResponse(
            f"<!doctype html><meta charset=utf-8><body style='font-family:sans-serif;"
            f"background:#0a0a0a;color:#eee;display:grid;place-items:center;height:100vh'>"
            f"<div style='text-align:center'><h2 style='color:{color}'>{msg}</h2>"
            f"<p>Vous pouvez fermer cet onglet et revenir à Spouet.</p></div>"
        )

    if error:
        return _page(f"Autorisation refusée : {error}", ok=False)
    if not code or not state:
        return _page("Requête invalide.", ok=False)

    cli = _redis()
    try:
        uid = await cli.get(f"spotify_oauth:{state}")
        await cli.delete(f"spotify_oauth:{state}")
    finally:
        await cli.aclose()
    if not uid:
        return _page("Session expirée, relancez la connexion.", ok=False)

    try:
        token_resp = await oauth.exchange_code(code)
        await client.store_tokens(db, UUID(uid), token_resp)
    except Exception as e:  # noqa: BLE001
        logger.warning("spotify.callback_failed", error=str(e))
        return _page(f"Échec de connexion : {e}", ok=False)
    logger.info("spotify.connected", user=uid)
    return _page("Spotify connecté ✓")


@router.get("/status")
async def spotify_status(user: CurrentUser, db: DbSession) -> dict:
    if not oauth.is_configured():
        return {"configured": False, "connected": False, "playback": None}
    connected = await client.is_connected(db, user.id)
    playback = None
    if connected:
        try:
            playback = await client.current_playback(db, user.id)
        except client.SpotifyError:
            playback = None
    return {"configured": True, "connected": connected, "playback": playback}


@router.post("/control")
async def control(payload: ControlIn, user: CurrentUser, db: DbSession) -> dict:
    a = payload.action.lower().strip()
    try:
        if a == "search":
            tracks = await client.search_tracks(db, user.id, payload.query or "", limit=5)
            return {"ok": True, "tracks": tracks}
        if a == "play":
            if payload.query:
                tracks = await client.search_tracks(db, user.id, payload.query, limit=1)
                if not tracks:
                    return {"ok": False, "message": "Aucun titre trouvé."}
                await client.play(db, user.id, uris=[tracks[0]["uri"]])
                return {"ok": True, "now_playing": tracks[0]}
            await client.play(db, user.id)
            return {"ok": True}
        if a == "pause":
            await client.pause(db, user.id)
            return {"ok": True}
        if a == "next":
            await client.next_track(db, user.id)
            return {"ok": True}
        if a == "previous":
            await client.previous_track(db, user.id)
            return {"ok": True}
        if a == "volume":
            await client.set_volume(db, user.id, payload.volume if payload.volume is not None else 50)
            return {"ok": True}
        if a == "status":
            return {"ok": True, "playback": await client.current_playback(db, user.id)}
        return {"ok": False, "message": f"Action inconnue : {a}"}
    except client.SpotifyError as e:
        return {"ok": False, "message": str(e)}


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(user: CurrentUser, db: DbSession) -> None:
    await client.disconnect(db, user.id)
