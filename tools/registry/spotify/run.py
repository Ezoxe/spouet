"""spotify : pilote la lecture Spotify via l'API backend Spouet."""

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
        print(json.dumps({"ok": False, "message": f"invalid json input: {e}"}))
        return 2

    action = args.get("action")
    if not action:
        print(json.dumps({"ok": False, "message": "action manquante"}))
        return 2

    base = os.environ.get("SPOUET_API_URL", "http://backend:8000").rstrip("/")
    token = os.environ.get("SPOUET_API_TOKEN")
    if not token:
        print(json.dumps({"ok": False, "message": "SPOUET_API_TOKEN missing"}))
        return 2

    body: dict[str, object] = {"action": action}
    if args.get("query") is not None:
        body["query"] = args["query"]
    if args.get("volume") is not None:
        body["volume"] = args["volume"]

    try:
        r = httpx.post(
            f"{base}/api/spotify/control",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=15,
        )
        r.raise_for_status()
        print(json.dumps(r.json(), ensure_ascii=False))
    except httpx.HTTPError as e:
        print(json.dumps({"ok": False, "message": f"backend error: {e}"}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
