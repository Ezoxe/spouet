"""spouet-discord-react : pose une réaction emoji sur un message Discord."""

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

    for required in ("external_id", "message_id", "emoji"):
        if not args.get(required):
            print(json.dumps({"error": f"missing {required!r}"}))
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
                "kind": "react",
                "external_id": args["external_id"],
                "message_id": args["message_id"],
                "emoji": args["emoji"],
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        r.raise_for_status()
        out = r.json()
    except httpx.HTTPError as e:
        print(json.dumps({"error": f"backend error: {e}"}))
        return 1

    print(json.dumps({"queued": bool(out.get("queued"))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
