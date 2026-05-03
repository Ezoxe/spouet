"""Client httpx async vers Ollama : streaming /api/chat."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


class OllamaError(RuntimeError):
    pass


async def chat_stream(
    base_url: str,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
    timeout_s: float = 600.0,
) -> AsyncIterator[dict[str, Any]]:
    """Stream `/api/chat` chunk par chunk.

    Chaque chunk Ollama est une ligne JSON. Yield ces dicts tels quels.
    """
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
    if options:
        payload["options"] = options

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        try:
            async with client.stream("POST", f"{base_url}/api/chat", json=payload) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise OllamaError(f"Ollama {resp.status_code}: {body.decode(errors='replace')}")
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    yield chunk
        except httpx.HTTPError as e:
            raise OllamaError(f"http error: {e}") from e


async def embed(base_url: str, *, model: str, texts: list[str]) -> list[list[float]]:
    """Embeddings batch via /api/embed."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{base_url}/api/embed",
            json={"model": model, "input": texts},
        )
        if resp.status_code >= 400:
            raise OllamaError(f"Ollama embed {resp.status_code}: {resp.text}")
        data = resp.json()
        return list(data.get("embeddings", []))
