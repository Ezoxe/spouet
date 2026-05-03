"""Client httpx async vers Ollama : streaming /api/chat."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx


class OllamaError(RuntimeError):
    pass


# Valeur sentinelle inscrite dans Node.agent_version pour distinguer les nodes
# enregistrés manuellement (pingés directement par le backend) de ceux qui
# tournent un node-agent (et envoient leur propre version dans le heartbeat).
DIRECT_AGENT_MARKER = "direct"


# Modèles Ollama connus comme supportant le tool calling natif.
# Doublé dans node-agent/spouet_agent/ollama.py : si tu modifies ici, modifie là-bas aussi.
_TOOL_CAPABLE_PREFIXES = (
    "llama3.1",
    "llama3.2",
    "llama3.3",
    "llama4",
    "qwen2.5",
    "qwen3",
    "mistral",
    "mistral-nemo",
    "mixtral",
    "command-r",
    "firefunction",
    "hermes",
)


@dataclass
class ProbedModel:
    name: str
    digest: str | None
    size_bytes: int | None
    parameter_size: str | None
    quant: str | None
    supports_tools: bool


@dataclass
class ProbeResult:
    reachable: bool
    error: str | None
    models: list[ProbedModel]


async def probe(base_url: str, *, timeout_s: float = 5.0) -> ProbeResult:
    """Joint un Ollama et liste ses modèles. Sert pour les nodes "direct" (sans agent)."""
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(f"{base_url}/api/tags")
            r.raise_for_status()
            data = r.json() or {}
    except httpx.HTTPError as e:
        return ProbeResult(reachable=False, error=str(e), models=[])
    except ValueError as e:
        return ProbeResult(reachable=False, error=f"invalid json: {e}", models=[])

    models: list[ProbedModel] = []
    for m in data.get("models", []):
        name = m.get("name") or m.get("model") or ""
        if not name:
            continue
        details = m.get("details") or {}
        models.append(
            ProbedModel(
                name=name,
                digest=m.get("digest"),
                size_bytes=m.get("size"),
                parameter_size=details.get("parameter_size"),
                quant=details.get("quantization_level"),
                supports_tools=any(name.startswith(p) for p in _TOOL_CAPABLE_PREFIXES),
            )
        )
    return ProbeResult(reachable=True, error=None, models=models)


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
