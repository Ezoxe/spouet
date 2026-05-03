"""Tool web-fetch : lit JSON sur stdin, écrit JSON sur stdout.

Convention Spouet : 1 invocation = 1 conteneur jetable. Erreurs en exit code != 0,
résultat sur stdout.
"""

from __future__ import annotations

import json
import sys

import httpx


def main() -> int:
    raw = sys.stdin.read()
    try:
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid json input: {e}"}))
        return 2

    url = args.get("url")
    max_bytes = int(args.get("max_bytes", 200_000))
    if not url or not isinstance(url, str):
        print(json.dumps({"error": "missing 'url'"}))
        return 2

    try:
        with httpx.Client(follow_redirects=True, timeout=20) as c:
            r = c.get(url)
            content = r.content[:max_bytes]
            truncated = len(r.content) > max_bytes
            text = content.decode(r.encoding or "utf-8", errors="replace")
        result = {
            "status": r.status_code,
            "text": text,
            "truncated": truncated,
            "final_url": str(r.url),
        }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except httpx.HTTPError as e:
        print(json.dumps({"error": f"http error: {e}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
