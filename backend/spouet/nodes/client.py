"""Client httpx async vers llama.cpp-server (API OpenAI-compatible) ou Ollama ≥ 0.1.14.

Les deux serveurs exposent /v1/chat/completions, /v1/models, /v1/embeddings.
Les chunks SSE sont normalisés vers le format interne attendu par chat_loop.py.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx


class LlamaError(RuntimeError):
    pass


# Rétrocompat pour les workers qui importent OllamaError
OllamaError = LlamaError

# Sentinelle pour les nodes enregistrés manuellement (pas de node-agent)
DIRECT_AGENT_MARKER = "direct"

# Modèles supportant les tool_calls — détection par nom de fichier GGUF ou tag Ollama
_TOOL_CAPABLE_PREFIXES = (
    "llama3.1", "llama3.2", "llama3.3", "llama4",
    "llama-3.1", "llama-3.2", "llama-3.3", "llama-4",
    "qwen2.5", "qwen3", "mistral", "mistral-nemo", "mixtral",
    "command-r", "firefunction", "hermes",
    # Liquid LFM2 / LFM2.5 (function calling natif) — "lfm2" matche aussi "lfm2.5".
    "lfm2",
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


def _model_supports_tools(name: str) -> bool:
    name_lower = name.lower()
    return any(p.lower() in name_lower for p in _TOOL_CAPABLE_PREFIXES)


async def probe(base_url: str, *, timeout_s: float = 5.0) -> ProbeResult:
    """Sonde un nœud (llama.cpp-server ou Ollama) et liste ses modèles.

    Essaie /v1/models (OpenAI-compatible, Ollama ≥ 0.1.14 + llama.cpp-server).
    Fallback sur /api/tags (Ollama legacy) si /v1/models est indisponible.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            # Tentative /v1/models
            try:
                r = await client.get(f"{base_url}/v1/models")
                if r.status_code == 200:
                    return _parse_v1_models(r.json())
            except httpx.HTTPError:
                pass

            # Fallback Ollama legacy
            r = await client.get(f"{base_url}/api/tags")
            r.raise_for_status()
            return _parse_ollama_tags(r.json())

    except httpx.HTTPError as e:
        return ProbeResult(reachable=False, error=str(e), models=[])
    except ValueError as e:
        return ProbeResult(reachable=False, error=f"invalid json: {e}", models=[])


def _parse_v1_models(data: dict[str, Any]) -> ProbeResult:
    """Parse la réponse /v1/models (OpenAI-compatible)."""
    models: list[ProbedModel] = []
    for m in data.get("data", []):
        name = m.get("id") or ""
        if not name:
            continue
        models.append(
            ProbedModel(
                name=name,
                digest=None,
                size_bytes=None,
                parameter_size=None,
                quant=None,
                supports_tools=_model_supports_tools(name),
            )
        )
    return ProbeResult(reachable=True, error=None, models=models)


def _parse_ollama_tags(data: dict[str, Any]) -> ProbeResult:
    """Parse la réponse /api/tags (Ollama legacy)."""
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
                supports_tools=_model_supports_tools(name),
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
    """Stream /v1/chat/completions.

    Les chunks SSE sont normalisés vers le format Ollama attendu par chat_loop.py :
      {"message": {"content": "...", "tool_calls": [...]}, "done": bool,
       "done_reason": str|None, "prompt_eval_count": int|None, "eval_count": int|None}
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        # Demande le bloc `usage` (prompt/completion tokens). En streaming OpenAI,
        # il n'est sinon jamais émis → tokens_in restait toujours None. llama-server
        # le renvoie dans un dernier chunk dédié (choices=[]). Un serveur qui ne
        # supporte pas l'option l'ignore simplement (fallback comptage local).
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = tools
    if options:
        # Options de génération au format Ollama (num_predict, temperature, top_p,
        # top_k, seed, stop…). Sans ce mapping elles étaient SILENCIEUSEMENT
        # ignorées : la classification mail tournait à la température serveur par
        # défaut (JSON peu fiable) et la génération n'était pas bornée.
        # num_predict → max_tokens (OpenAI) ; le reste est accepté tel quel par
        # llama-server (top_k, repeat_penalty, min_p… en plus des champs OpenAI).
        opts = dict(options)
        num_predict = opts.pop("num_predict", None)
        if num_predict is not None:
            payload["max_tokens"] = num_predict
        payload.update(opts)

    # Accumulation des tool_calls sur plusieurs chunks (OpenAI streaming incrémental)
    accumulated_tool_calls: dict[int, dict[str, Any]] = {}

    # Timeout fin : connect court (fail-fast si llama-server down),
    # read long (le streaming peut durer plusieurs minutes).
    timeout = httpx.Timeout(connect=5.0, read=timeout_s, write=10.0, pool=5.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream(
                "POST", f"{base_url}/v1/chat/completions", json=payload
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    # Borne la longueur du body : llama-server peut renvoyer
                    # plusieurs MB d'erreur, on n'a pas besoin de tout logger.
                    body_text = body.decode(errors="replace")[:2000]
                    raise LlamaError(f"llama-server {resp.status_code}: {body_text}")

                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    normalized = _normalize_chunk(chunk, accumulated_tool_calls)
                    if normalized is not None:
                        yield normalized

        except httpx.ConnectError as e:
            raise LlamaError(
                f"llama-server injoignable sur {base_url} — "
                f"aucun modèle n'est chargé sur ce node ({e})"
            ) from e
        except httpx.HTTPError as e:
            raise LlamaError(f"http error talking to {base_url}: {e}") from e


def _normalize_chunk(
    chunk: dict[str, Any],
    acc_tool_calls: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    """Convertit un chunk SSE OpenAI vers le format interne Ollama-like."""
    choices = chunk.get("choices", [])
    usage: dict[str, Any] = chunk.get("usage") or {}
    if not choices:
        # Dernier chunk de stream_options.include_usage : aucun delta, seulement
        # les compteurs de tokens. On le propage comme un événement `done` léger
        # afin que la boucle de chat enregistre prompt_eval_count / eval_count.
        if usage:
            return {
                "message": {"role": "assistant", "content": "", "reasoning": "", "tool_calls": None},
                "done": True,
                "done_reason": None,
                "prompt_eval_count": usage.get("prompt_tokens"),
                "eval_count": usage.get("completion_tokens"),
            }
        return None

    choice = choices[0]
    delta = choice.get("delta", {})
    finish_reason: str | None = choice.get("finish_reason")

    content = delta.get("content") or ""
    # Raisonnement des modèles « thinking » (Gemma, Qwen3, DeepSeek-R1…) : avec
    # --reasoning-format auto (défaut llama-server), le <think> est extrait dans
    # `reasoning_content` plutôt que laissé inline. Sans le forwarder, on perdait
    # tout le raisonnement (l'UI n'affichait que la réponse finale).
    reasoning = delta.get("reasoning_content") or ""

    # Accumulation des tool_calls (OpenAI stream les envoie par morceaux)
    raw_tcs = delta.get("tool_calls")
    if raw_tcs:
        for tc in raw_tcs:
            idx = tc.get("index", 0)
            if idx not in acc_tool_calls:
                acc_tool_calls[idx] = {
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                }
            fn = tc.get("function", {})
            if fn.get("name"):
                acc_tool_calls[idx]["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                acc_tool_calls[idx]["function"]["arguments"] += fn["arguments"]

    tool_calls: list[dict[str, Any]] | None = None
    if finish_reason in ("tool_calls", "stop") and acc_tool_calls:
        # Émet les tool_calls complets dans l'ordre des index OpenAI.
        # Convertit arguments JSON string → dict.
        tool_calls = []
        for idx in sorted(acc_tool_calls.keys()):
            tc = acc_tool_calls[idx]
            args = tc["function"].get("arguments", "{}")
            try:
                parsed_args = json.loads(args) if isinstance(args, str) else args
            except json.JSONDecodeError:
                parsed_args = {}
            tool_calls.append({
                "type": "function",
                "function": {"name": tc["function"]["name"], "arguments": parsed_args},
            })

    done = finish_reason is not None
    return {
        "message": {
            "role": delta.get("role", "assistant"),
            "content": content,
            "reasoning": reasoning,
            "tool_calls": tool_calls,
        },
        "done": done,
        "done_reason": finish_reason,
        "prompt_eval_count": usage.get("prompt_tokens"),
        "eval_count": usage.get("completion_tokens"),
    }


async def embed(base_url: str, *, model: str, texts: list[str]) -> list[list[float]]:
    """Embeddings via /v1/embeddings (OpenAI-compatible) ou /api/embed (Ollama legacy)."""
    async with httpx.AsyncClient(timeout=120) as client:
        # Essaie /v1/embeddings
        try:
            resp = await client.post(
                f"{base_url}/v1/embeddings",
                json={"model": model, "input": texts},
            )
            if resp.status_code == 200:
                data = resp.json()
                return [item["embedding"] for item in sorted(data.get("data", []), key=lambda x: x.get("index", 0))]
        except httpx.HTTPError:
            pass

        # Fallback Ollama
        resp = await client.post(
            f"{base_url}/api/embed",
            json={"model": model, "input": texts},
        )
        if resp.status_code >= 400:
            raise LlamaError(f"embed {resp.status_code}: {resp.text}")
        data = resp.json()
        return list(data.get("embeddings", []))
