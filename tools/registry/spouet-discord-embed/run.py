"""spouet-discord-embed : envoie un embed Discord via le bridge backend."""

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

    external_id = args.get("external_id")
    if not external_id:
        print(json.dumps({"error": "missing 'external_id'"}))
        return 2

    embed: dict = {k: v for k, v in args.items() if k != "external_id"}
    if not embed.get("title") and not embed.get("description"):
        print(json.dumps({"error": "embed needs at least title or description"}))
        return 2

    base = os.environ.get("SPOUET_API_URL", "http://backend:8000").rstrip("/")
    token = os.environ.get("SPOUET_API_TOKEN")
    if not token:
        print(json.dumps({"error": "SPOUET_API_TOKEN missing"}))
        return 2

    try:
        r = httpx.post(
            f"{base}/api/connectors/discord-bot/outbound",
            json={
                "kind": "send_embed",
                "external_id": external_id,
                "content_json": embed,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        r.raise_for_status()
        out = r.json()
    except httpx.HTTPError as e:
        print(json.dumps({"error": f"backend error: {e}"}))
        return 1

    print(json.dumps({"queued": bool(out.get("queued")), "connector_id": out.get("connector_id")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
