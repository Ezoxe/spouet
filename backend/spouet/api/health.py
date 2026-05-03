"""Healthcheck endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from spouet import __version__
from spouet.api.deps import DbSession

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
