"""Client httpx vers le microservice `image-engine`.

Le backend ne fait *que* proxifier : l'auth/quotas sont gérés côté API Spouet,
image-engine reste un service interne sans authentification propre.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from spouet.core.config import settings
from spouet.core.logging import get_logger

logger = get_logger(__name__)


class ImageEngineError(RuntimeError):
    """image-engine injoignable ou a renvoyé une erreur."""


@dataclass(frozen=True)
class GenerateParams:
    prompt: str
    negative_prompt: str | None = None
    width: int | None = None
    height: int | None = None
    steps: int | None = None
    guidance_scale: float | None = None
    seed: int | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"prompt": self.prompt}
        for key in ("negative_prompt", "width", "height", "steps", "guidance_scale", "seed"):
            val = getattr(self, key)
            if val is not None:
                payload[key] = val
        return payload


def _base() -> str:
    return settings.image_engine_url.rstrip("/")


async def generate(params: GenerateParams) -> bytes:
    """Demande une image à image-engine et renvoie ses octets PNG."""
    try:
        async with httpx.AsyncClient(timeout=settings.image_timeout_s) as client:
            resp = await client.post(f"{_base()}/generate", json=params.to_payload())
    except httpx.HTTPError as e:
        raise ImageEngineError(f"image-engine injoignable: {e}") from e
    if resp.status_code != 200:
        raise ImageEngineError(f"generate {resp.status_code}: {resp.text[:200]}")
    ct = resp.headers.get("content-type", "")
    if not ct.startswith("image/"):
        raise ImageEngineError(f"réponse inattendue (content-type={ct!r})")
    return resp.content


async def health() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_base()}/health")
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise ImageEngineError(f"image-engine injoignable: {e}") from e
    return resp.json()
