"""Récupération des tool calls émis en TEXTE par le modèle.

Certains modèles GGUF (templates de chat non reconnus par llama-server, quants
exotiques…) n'émettent pas leurs appels d'outils via le canal structuré
`tool_calls` : ils les écrivent en clair dans le contenu, p.ex. ::

    <|tool_call>call:web_search{query:<|"|>météo Paris<|"|>}<tool_call|>
    <tool_call>{"name": "web_search", "arguments": {"query": "..."}}</tool_call>
    {"name": "web_search", "arguments": {"query": "..."}}

llama-server ne les parse alors pas → le tool n'est jamais exécuté, l'appel
« fuit » à l'écran. Ce module détecte ces formats en dernier recours, les
convertit au format interne attendu par chat_loop, et renvoie le contenu nettoyé.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Noms d'outils plausibles (snake/kebab case). On évite de capturer n'importe quoi.
_NAME_RE = r"[a-zA-Z_][a-zA-Z0-9_\-]{1,63}"


def _clean_noise(s: str) -> str:
    """Neutralise les pseudo-tokens spéciaux qui polluent les arguments."""
    s = s.replace('<|"|>', '"').replace("<|'|>", "'")
    # Retire les marqueurs <|...|> et <tool_call|> / <|tool_call> résiduels.
    s = re.sub(r"<\|?/?tool_call\|?>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<\|[^>]*\|>", "", s)
    return s


def _try_json(raw: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _parse_args(raw: str) -> dict[str, Any]:
    """Parse un bloc d'arguments en dict, tolérant (JSON ou clé:valeur lâche)."""
    cleaned = _clean_noise(raw).strip()
    if not cleaned:
        return {}
    # 1) JSON direct ou enveloppé.
    obj = _try_json(cleaned) or _try_json("{" + cleaned + "}")
    if obj is not None:
        return obj
    # 2) Paires clé:valeur / clé=valeur séparées par des virgules (hors crochets).
    args: dict[str, Any] = {}
    parts = re.split(r",(?![^\[\]{}]*[\]}])", cleaned)
    for part in parts:
        m = re.match(rf'\s*["\']?({_NAME_RE})["\']?\s*[:=]\s*(.*)', part, re.DOTALL)
        if not m:
            continue
        key = m.group(1).strip()
        val = m.group(2).strip().strip("\"'").strip()
        if val:
            args[key] = val
    return args


def _mk_call(name: str, args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        args = {}
    return {"type": "function", "function": {"name": name, "arguments": args}}


def salvage_tool_calls(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Détecte d'éventuels tool calls en texte. Retourne (contenu_nettoyé, calls).

    `calls` est au format interne ({"type":"function","function":{name, arguments}}).
    Vide si rien de plausible. Le contenu nettoyé retire les segments capturés.
    """
    if not text or ("{" not in text and "call" not in text.lower()):
        return text, []

    calls: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []

    # A) Bloc <tool_call> … </tool_call> (ou pseudo-tokens) contenant du JSON.
    for m in re.finditer(
        r"<\|?\/?tool_call\|?>?\s*(\{.*?\})\s*<\|?\/?tool_call\|?>?",
        text,
        re.DOTALL | re.IGNORECASE,
    ):
        obj = _try_json(_clean_noise(m.group(1)))
        if obj and obj.get("name"):
            calls.append(_mk_call(obj["name"], obj.get("arguments") or obj.get("parameters") or {}))
            spans.append(m.span())

    # B) Format `call:NAME{...}` (avec d'éventuels marqueurs autour).
    if not calls:
        for m in re.finditer(rf"call\s*:\s*({_NAME_RE})\s*\{{(.*?)\}}", text, re.DOTALL):
            calls.append(_mk_call(m.group(1), _parse_args(m.group(2))))
            spans.append(m.span())

    # C) JSON nu {"name": "...", "arguments"/"parameters": {...}}.
    if not calls:
        for m in re.finditer(
            rf'\{{[^{{}}]*?"name"\s*:\s*"({_NAME_RE})"[^{{}}]*?\}}', text, re.DOTALL
        ):
            obj = _try_json(m.group(0))
            if obj and obj.get("name"):
                calls.append(
                    _mk_call(obj["name"], obj.get("arguments") or obj.get("parameters") or {})
                )
                spans.append(m.span())

    if not calls:
        return text, []

    # Retire les segments capturés + d'éventuels marqueurs orphelins → contenu propre.
    cleaned = text
    for start, end in sorted(spans, key=lambda s: s[0], reverse=True):
        cleaned = cleaned[:start] + cleaned[end:]
    cleaned = re.sub(r"<\|?\/?tool_call\|?>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<\|[^>]*\|>", "", cleaned).strip()

    return cleaned, calls
