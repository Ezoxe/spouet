"""spouet-nodes-status : liste les nodes du cluster avec leurs métriques."""

from __future__ import annotations

import json
import os
import sys

import httpx


def main() -> int:
    raw = sys.stdin.read()
    try:
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid json input: {e}"}))
        return 2

    only_online = bool(args.get("only_online", False))
    base = os.environ.get("SPOUET_API_URL", "http://backend:8000").rstrip("/")
    token = os.environ.get("SPOUET_API_TOKEN")
    if not token:
        print(json.dumps({"error": "SPOUET_API_TOKEN missing"}))
        return 2

    try:
        r = httpx.get(
            f"{base}/api/nodes",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        r.raise_for_status()
        nodes = r.json()
    except httpx.HTTPError as e:
        print(json.dumps({"error": f"backend error: {e}"}))
        return 1

    out_nodes = []
    online = 0
    for n in nodes:
        if only_online and n.get("status") != "online":
            continue
        if n.get("status") == "online":
            online += 1
        caps = n.get("capabilities") or {}
        out_nodes.append(
            {
                "name": n.get("name"),
                "status": n.get("status"),
                "gpu_model": n.get("gpu_model"),
                "vram_used_mb": n.get("vram_used_mb"),
                "vram_total_mb": n.get("vram_total_mb"),
                "ram_used_mb": n.get("ram_used_mb"),
                "ram_total_mb": n.get("ram_total_mb"),
                "llama_tps": n.get("llama_tps"),
                "llama_model_loaded": n.get("llama_model_loaded"),
                "compute_class": caps.get("compute_class"),
            }
        )

    print(
        json.dumps(
            {
                "nodes": out_nodes,
                "online_count": online,
                "total_count": len(nodes),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
