"""spouet-node-metrics : stats agrégées d'un node sur une plage."""

from __future__ import annotations

import json
import os
import sys

import httpx


def _avg(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def main() -> int:
    raw = sys.stdin.read()
    try:
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid json input: {e}"}))
        return 2

    node_name = args.get("node_name")
    if not node_name:
        print(json.dumps({"error": "missing 'node_name'"}))
        return 2
    range_ = args.get("range", "24h")
    if range_ not in ("1h", "6h", "24h", "7d"):
        print(json.dumps({"error": f"unknown range {range_!r}"}))
        return 2

    base = os.environ.get("SPOUET_API_URL", "http://backend:8000").rstrip("/")
    token = os.environ.get("SPOUET_API_TOKEN")
    if not token:
        print(json.dumps({"error": "SPOUET_API_TOKEN missing"}))
        return 2

    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=10, headers=headers) as c:
            r = c.get(f"{base}/api/nodes")
            r.raise_for_status()
            nodes = r.json()
            node = next((n for n in nodes if n.get("name") == node_name), None)
            if node is None:
                print(json.dumps({"error": f"node {node_name!r} not found"}))
                return 1
            r = c.get(f"{base}/api/nodes/{node['id']}/metrics", params={"range": range_})
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        print(json.dumps({"error": f"backend error: {e}"}))
        return 1

    series = data.get("series") or []
    stats = {
        "tps_avg": _avg([p.get("llama_tps") for p in series]),
        "tps_max": max((p.get("llama_tps") or 0) for p in series) if series else None,
        "cpu_pct_avg": _avg([p.get("cpu_pct") for p in series]),
        "ram_used_mb_max": max((p.get("ram_used_mb") or 0) for p in series) if series else None,
        "vram_used_mb_max": max((p.get("vram_used_mb") or 0) for p in series) if series else None,
    }
    print(
        json.dumps(
            {
                "node_name": node_name,
                "range": range_,
                "point_count": len(series),
                "stats": stats,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
