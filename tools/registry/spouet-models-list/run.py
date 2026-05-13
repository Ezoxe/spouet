"""spouet-models-list : modèles disponibles et leur emplacement."""

from __future__ import annotations

import json
import os
import sys

import httpx


def main() -> int:
    sys.stdin.read()  # consomme stdin (pas de paramètres)
    base = os.environ.get("SPOUET_API_URL", "http://backend:8000").rstrip("/")
    token = os.environ.get("SPOUET_API_TOKEN")
    if not token:
        print(json.dumps({"error": "SPOUET_API_TOKEN missing"}))
        return 2

    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=10, headers=headers) as c:
            nodes = c.get(f"{base}/api/nodes").raise_for_status().json()
            agg = c.get(f"{base}/api/nodes/models").raise_for_status().json()
    except httpx.HTTPError as e:
        print(json.dumps({"error": f"backend error: {e}"}))
        return 1

    name_to_loaded_nodes: dict[str, set[str]] = {}
    for n in nodes:
        m = n.get("llama_model_loaded")
        if m:
            name_to_loaded_nodes.setdefault(m, set()).add(n.get("name") or "?")

    out = []
    for m in agg:
        loaded_on = name_to_loaded_nodes.get(m.get("name"), set())
        out.append(
            {
                "name": m.get("name"),
                "supports_tools": bool(m.get("supports_tools")),
                "nodes": [
                    {"name": n.get("name"), "loaded": n.get("name") in loaded_on}
                    for n in (m.get("nodes") or [])
                ],
            }
        )
    print(json.dumps({"models": out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
