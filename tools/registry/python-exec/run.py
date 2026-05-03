"""Exécute du code Python dans un namespace isolé (le conteneur Docker fait l'isolation système)."""

from __future__ import annotations

import io
import json
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout


def main() -> int:
    raw = sys.stdin.read()
    try:
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid json input: {e}"}))
        return 2

    code = args.get("code")
    if not isinstance(code, str) or not code:
        print(json.dumps({"error": "missing 'code'"}))
        return 2

    ns: dict = {"result": None}
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    error: str | None = None

    try:
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            exec(code, ns)
    except Exception:  # noqa: BLE001
        error = traceback.format_exc(limit=5)

    payload = {
        "result": _safe_json(ns.get("result")),
        "stdout": out_buf.getvalue(),
        "stderr": err_buf.getvalue(),
    }
    if error:
        payload["error"] = error

    print(json.dumps(payload, ensure_ascii=False, default=str))
    return 0 if error is None else 1


def _safe_json(obj):  # type: ignore[no-untyped-def]
    """Convertit ce qui n'est pas sérialisable en str."""
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)


if __name__ == "__main__":
    sys.exit(main())
