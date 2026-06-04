"""Client httpx vers l'API image d'un node-agent (port `image_port`).

La génération tourne sur le node (machine GPU), pas sur l'admin. Le backend ne
fait que proxifier : l'auth/quotas sont gérés côté API Spouet, l'API image du
node est interne au LAN. `base_url` = http://{node.host}:{node.image_port}.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from spouet.core.config import settings
from spouet.core.logging import get_logger

logger = get_logger(__name__)


class ImageEngineError(RuntimeError):
    """API image du node injoignable ou a renvoyé une erreur."""


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


def _norm(base_url: str) -> str:
    return base_url.rstrip("/")


async def generate(base_url: str, params: GenerateParams) -> bytes:
    """Demande une image au node et renvoie ses octets PNG."""
    try:
        async with httpx.AsyncClient(timeout=settings.image_timeout_s) as client:
            resp = await client.post(f"{_norm(base_url)}/generate", json=params.to_payload())
    except httpx.HTTPError as e:
        raise ImageEngineError(f"node image injoignable: {e}") from e
    if resp.status_code != 200:
        raise ImageEngineError(f"generate {resp.status_code}: {resp.text[:200]}")
    ct = resp.headers.get("content-type", "")
    if not ct.startswith("image/"):
        raise ImageEngineError(f"réponse inattendue (content-type={ct!r})")
    return resp.content


async def health(base_url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_norm(base_url)}/health")
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise ImageEngineError(f"node image injoignable: {e}") from e
    return resp.json()


async def status(base_url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_norm(base_url)}/status")
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise ImageEngineError(f"node image injoignable: {e}") from e
    return resp.json()


async def pull(base_url: str, model: str, hf_token: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model}
    if hf_token:
        payload["hf_token"] = hf_token
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{_norm(base_url)}/pull", json=payload)
    except httpx.HTTPError as e:
        raise ImageEngineError(f"node image injoignable: {e}") from e
    if resp.status_code >= 400:
        raise ImageEngineError(f"pull {resp.status_code}: {resp.text[:200]}")
    return resp.json()


async def pull_status(base_url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_norm(base_url)}/pull/status")
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise ImageEngineError(f"node image injoignable: {e}") from e
    return resp.json()


async def load(base_url: str, model: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if model:
        payload["model"] = model
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{_norm(base_url)}/load", json=payload)
    except httpx.HTTPError as e:
        raise ImageEngineError(f"node image injoignable: {e}") from e
    if resp.status_code >= 400:
        raise ImageEngineError(f"load {resp.status_code}: {resp.text[:200]}")
    return resp.json()
