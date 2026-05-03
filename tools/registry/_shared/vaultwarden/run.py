"""Wrapper bw CLI pour les tools Vaultwarden.

L'opération est sélectionnée par la variable d'env ``BW_OP`` (``list``, ``get``,
``set``). Les credentials viennent du coffre Spouet via les variables d'env
``VAULTWARDEN_URL``, ``VAULTWARDEN_EMAIL``, ``VAULTWARDEN_PASSWORD``.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def _fail(msg: str) -> "None":
    _emit({"error": msg})
    sys.exit(0)  # exit 0 pour que stdout JSON soit lu par l'orchestrateur


def _bw(*args: str, env: dict[str, str] | None = None, capture: bool = True) -> subprocess.CompletedProcess[str]:
    e = os.environ.copy()
    e.setdefault("BITWARDENCLI_APPDATA_DIR", "/tmp/bwconfig")
    if env:
        e.update(env)
    return subprocess.run(
        ["bw", *args],
        capture_output=capture,
        text=True,
        env=e,
        check=False,
    )


def _login(email: str, password: str) -> str:
    """Login si besoin, retourne BW_SESSION."""
    r = _bw("login", email, "--raw", "--passwordenv", "BW_PASS",
            env={"BW_PASS": password})
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    err = (r.stderr or "").lower()
    if "already logged in" in err or "you are already logged in" in err:
        r = _bw("unlock", "--raw", "--passwordenv", "BW_PASS",
                env={"BW_PASS": password})
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    _fail(f"bw login failed: {(r.stderr or r.stdout).strip()}")
    return ""  # unreachable


def _op_list(args: dict[str, Any], session: str) -> dict[str, Any]:
    env = {"BW_SESSION": session}
    q = (args.get("search") or "").strip()
    cmd = ("list", "items", "--search", q) if q else ("list", "items")
    r = _bw(*cmd, env=env)
    if r.returncode != 0:
        _fail(f"bw list: {(r.stderr or '').strip()}")
    items = json.loads(r.stdout or "[]")
    out = []
    for it in items:
        login = it.get("login") or {}
        uris = login.get("uris") or []
        out.append({
            "id": it.get("id"),
            "name": it.get("name"),
            "username": login.get("username"),
            "uri": (uris[0].get("uri") if uris else None),
            "folder_id": it.get("folderId"),
        })
    return {"items": out, "count": len(out)}


def _op_get(args: dict[str, Any], session: str) -> dict[str, Any]:
    env = {"BW_SESSION": session}
    ref = (args.get("id_or_name") or "").strip()
    if not ref:
        _fail("missing 'id_or_name'")
    r = _bw("get", "item", ref, env=env)
    if r.returncode != 0:
        _fail(f"bw get: {(r.stderr or '').strip()}")
    it = json.loads(r.stdout)
    login = it.get("login") or {}
    uris = login.get("uris") or []
    return {
        "id": it.get("id"),
        "name": it.get("name"),
        "username": login.get("username"),
        "password": login.get("password"),
        "totp": login.get("totp"),
        "notes": it.get("notes"),
        "uri": (uris[0].get("uri") if uris else None),
    }


def _op_set(args: dict[str, Any], session: str) -> dict[str, Any]:
    env = {"BW_SESSION": session}
    name = (args.get("name") or "").strip()
    if not name:
        _fail("missing 'name'")
    username = args.get("username")
    password = args.get("password")
    notes = args.get("notes")
    uri = args.get("uri")

    # Recherche d'un item existant portant exactement ce nom
    existing = None
    r = _bw("list", "items", "--search", name, env=env)
    if r.returncode == 0:
        for it in json.loads(r.stdout or "[]"):
            if (it.get("name") or "").strip().lower() == name.lower():
                existing = it
                break

    item: dict[str, Any] = {
        "type": 1,
        "name": name,
        "notes": notes,
        "login": {
            "username": username,
            "password": password,
            "uris": [{"match": None, "uri": uri}] if uri else [],
        },
    }

    if existing is not None:
        item["id"] = existing["id"]
        # On préserve le folder
        item["folderId"] = existing.get("folderId")
        payload = base64.b64encode(json.dumps(item).encode("utf-8")).decode()
        r = _bw("edit", "item", existing["id"], payload, env=env)
        action = "updated"
    else:
        payload = base64.b64encode(json.dumps(item).encode("utf-8")).decode()
        r = _bw("create", "item", payload, env=env)
        action = "created"

    if r.returncode != 0:
        _fail(f"bw {action}: {(r.stderr or '').strip()}")

    result = json.loads(r.stdout) if r.stdout.strip() else {}
    return {"id": result.get("id"), "action": action}


def main() -> None:
    op = (os.environ.get("BW_OP") or "").strip()
    if op not in {"list", "get", "set"}:
        _fail(f"BW_OP must be list|get|set, got {op!r}")

    raw = sys.stdin.read()
    try:
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        _fail(f"invalid JSON args: {e}")
        return

    url = os.environ.get("VAULTWARDEN_URL", "").strip()
    email = os.environ.get("VAULTWARDEN_EMAIL", "").strip()
    password = os.environ.get("VAULTWARDEN_PASSWORD", "").strip()
    if not (url and email and password):
        _fail("missing VAULTWARDEN_URL / VAULTWARDEN_EMAIL / VAULTWARDEN_PASSWORD")

    os.makedirs("/tmp/bwconfig", exist_ok=True)

    r = _bw("config", "server", url)
    if r.returncode != 0:
        _fail(f"bw config server: {(r.stderr or '').strip()}")

    session = _login(email, password)
    _bw("sync", env={"BW_SESSION": session})

    handlers = {"list": _op_list, "get": _op_get, "set": _op_set}
    try:
        out = handlers[op](args, session)
    except Exception as e:  # noqa: BLE001
        _fail(f"{op} failed: {e}")
        return

    _emit(out)


if __name__ == "__main__":
    main()
