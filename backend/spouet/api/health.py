"""Healthcheck endpoints.

`/api/health` reste public et minimal (test liveness — surveillé par Docker,
load balancer, monitoring externe).

`/api/health/diagnostics` est protégé (auth requise) et vérifie en profondeur :
DB, Redis, runtime Docker. Utile pour le panneau admin / le bouton "tester"
de l'install.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from spouet import __version__
from spouet.api.deps import CurrentUser, DbSession
from spouet.core.config import settings

router = APIRouter()


@router.get("/health")
async def health(db: DbSession) -> dict[str, object]:
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok", "version": __version__, "db": db_ok}


async def _check_redis() -> dict[str, Any]:
    try:
        import redis.asyncio as redis  # type: ignore[import-untyped]

        client = redis.from_url(str(settings.redis_url), decode_responses=True)
        try:
            pong = await asyncio.wait_for(client.ping(), timeout=2.0)
            return {"ok": bool(pong), "error": None}
        finally:
            await client.aclose()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _check_docker_sync() -> dict[str, Any]:
    try:
        import docker  # type: ignore[import-untyped]

        client = docker.from_env(timeout=2)
        version = client.version().get("Version") or "unknown"
        return {"ok": True, "error": None, "version": version}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "version": None}


async def _check_docker() -> dict[str, Any]:
    return await asyncio.to_thread(_check_docker_sync)


@router.get("/health/diagnostics")
async def diagnostics(_: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Vérification approfondie : DB, Redis, Docker. Requiert auth.

    Retourne un dict avec `status: ok|degraded` selon que tous les composants
    répondent. Le frontend peut s'en servir pour un panneau "santé" admin.
    """
    db_check: dict[str, Any] = {"ok": False, "error": None}
    try:
        await db.execute(text("SELECT 1"))
        db_check["ok"] = True
    except Exception as e:  # noqa: BLE001
        db_check["error"] = f"{type(e).__name__}: {e}"

    redis_check, docker_check = await asyncio.gather(
        _check_redis(), _check_docker(), return_exceptions=False
    )

    all_ok = db_check["ok"] and redis_check["ok"] and docker_check["ok"]
    return {
        "status": "ok" if all_ok else "degraded",
        "version": __version__,
        "components": {
            "database": db_check,
            "redis": redis_check,
            "docker": docker_check,
        },
    }
