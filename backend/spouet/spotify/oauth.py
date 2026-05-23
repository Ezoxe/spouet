"""OAuth Spotify (Authorization Code) : URL d'autorisation, échange, refresh."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import urlencode

import httpx

from spouet.core.config import settings

# Scopes nécessaires pour lire et contrôler la lecture (Spotify Connect).
SCOPES = (
    "user-read-playback-state user-modify-playback-state "
    "user-read-currently-playing streaming"
)
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"


class SpotifyAuthError(RuntimeError):
    """Échec d'un échange/rafraîchissement de token."""


def is_configured() -> bool:
    return bool(
        settings.spotify_client_id
        and settings.spotify_client_secret
        and settings.spotify_redirect_uri
    )


def authorize_url(state: str) -> str:
    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _basic_auth() -> str:
    raw = f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()
    return base64.b64encode(raw).decode()


async def _token_request(data: dict[str, str]) -> dict[str, Any]:
    headers = {
        "Authorization": f"Basic {_basic_auth()}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(TOKEN_URL, data=data, headers=headers)
    except httpx.HTTPError as e:
        raise SpotifyAuthError(f"Spotify injoignable: {e}") from e
    if r.status_code != 200:
        raise SpotifyAuthError(f"token {r.status_code}: {r.text[:200]}")
    return r.json()


async def exchange_code(code: str) -> dict[str, Any]:
    return await _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.spotify_redirect_uri,
        }
    )


async def refresh_token(refresh: str) -> dict[str, Any]:
    return await _token_request({"grant_type": "refresh_token", "refresh_token": refresh})
