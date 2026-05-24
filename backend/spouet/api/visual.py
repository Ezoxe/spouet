"""Proxy d'images : récupère une image distante côté serveur et la renvoie.

Permet à l'overlay desktop d'afficher des images (résultats de recherche) sans
soucis de mixed-content/CORS, avec un cache navigateur. Requiert l'auth ; le
frontend fetch l'URL puis crée un blob (un ``<img src>`` ne peut pas porter le
header Authorization).
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Response, status

from spouet.api.deps import CurrentUser
from spouet.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

_MAX_BYTES = 10 * 1024 * 1024
_TIMEOUT_S = 10


@router.get("/proxy")
async def proxy(url: str, _: CurrentUser) -> Response:
    """Récupère ``url`` (image http/https) et la renvoie. Auth requise.

    Note SSRF : l'endpoint est protégé par auth (utilisateur connecté) et limité
    aux réponses ``image/*``. Pour un usage personnel self-hosted, acceptable.
    """
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "url http(s) requise")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Spouet/1.0"})
            r.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("visual.proxy_failed", error=str(e))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "image inaccessible") from e

    ct = r.headers.get("content-type", "")
    if not ct.startswith("image/"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "la cible n'est pas une image")
    if len(r.content) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "image trop lourde")
    return Response(
        content=r.content,
        media_type=ct,
        headers={"Cache-Control": "public, max-age=3600"},
    )
