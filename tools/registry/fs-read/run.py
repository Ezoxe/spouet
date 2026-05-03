"""Lit un fichier sous /workspace (le mount est géré par l'orchestrateur)."""

from __future__ import annotations

import json
import os
import sys

ROOT = "/workspace"


def main() -> int:
    raw = sys.stdin.read()
    try:
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid json input: {e}"}))
        return 2

    rel = args.get("path")
    max_bytes = int(args.get("max_bytes", 100_000))
    if not isinstance(rel, str) or not rel:
        print(json.dumps({"error": "missing 'path'"}))
        return 2
    if ".." in rel.split("/") or rel.startswith("/"):
        print(json.dumps({"error": "invalid path"}))
        return 2

    abspath = os.path.normpath(os.path.join(ROOT, rel))
    if not abspath.startswith(ROOT + os.sep) and abspath != ROOT:
        print(json.dumps({"error": "path escapes /workspace"}))
        return 2

    try:
        with open(abspath, "rb") as f:
            data = f.read(max_bytes + 1)
    except FileNotFoundError:
        print(json.dumps({"error": "file not found"}))
        return 1
    except OSError as e:
        print(json.dumps({"error": f"io error: {e}"}))
        return 1

    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    text = data.decode("utf-8", errors="replace")
    print(
        json.dumps(
            {"text": text, "bytes_read": len(data), "truncated": truncated},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
