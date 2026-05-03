"""Client Ollama léger (juste ce qu'il faut pour le heartbeat)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

# Modèles connus comme supportant le tool calling natif
TOOL_CAPABLE_PREFIXES = (
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
class OllamaModel:
    name: str
    digest: str | None
    size_bytes: int | None
    parameter_size: str | None
    quant: str | None
    supports_tools: bool


async def list_models(base_url: str, client: httpx.AsyncClient) -> list[OllamaModel]:
    r = await client.get(f"{base_url}/api/tags", timeout=5)
    r.raise_for_status()
    data = r.json() or {}
    out: list[OllamaModel] = []
    for m in data.get("models", []):
        name = m.get("name") or m.get("model") or ""
        if not name:
            continue
        details = m.get("details") or {}
        out.append(
            OllamaModel(
                name=name,
                digest=m.get("digest"),
                size_bytes=m.get("size"),
                parameter_size=details.get("parameter_size"),
                quant=details.get("quantization_level"),
                supports_tools=any(name.startswith(p) for p in TOOL_CAPABLE_PREFIXES),
            )
        )
    return out
