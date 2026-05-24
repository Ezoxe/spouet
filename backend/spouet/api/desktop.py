"""API desktop : capacités du client (hello), résultats d'actions, CRUD macros.

Le client Tauri POST ``/hello`` périodiquement (ses capacités : écrans, apps),
et ``/actions/{id}/result`` pour renvoyer le résultat d'une action demandée par
l'orchestrator. Les macros sont aussi gérables depuis l'UI web (page /macros).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.db.models import DesktopMacro
from spouet.desktop import bridge, registry
from spouet.orchestrator import builtin_tools

router = APIRouter()


# ---------------------------------------------------------------------------
# Capacités du client connecté
# ---------------------------------------------------------------------------


class HelloIn(BaseModel):
    os: str = ""
    version: str | None = None
    monitors: list[dict[str, Any]] = Field(default_factory=list)
    apps: list[Any] = Field(default_factory=list)


@router.post("/hello")
async def hello(payload: HelloIn, user: CurrentUser) -> dict[str, Any]:
    """Heartbeat du client desktop : publie ses capacités (TTL côté registry)."""
    await registry.set_caps(user.id, payload.model_dump())
    return {"ok": True}


@router.get("/capabilities")
async def capabilities(user: CurrentUser) -> dict[str, Any]:
    """État courant : un client desktop est-il connecté ? quels écrans / apps ?"""
    caps = await registry.get_caps(user.id)
    return {
        "connected": caps is not None,
        "os": (caps or {}).get("os"),
        "version": (caps or {}).get("version"),
        "monitors": (caps or {}).get("monitors", []),
        "apps": registry.known_app_names(caps),
    }


# ---------------------------------------------------------------------------
# Résultats d'actions desktop (renvoyés par le client)
# ---------------------------------------------------------------------------


@router.post("/actions/{request_id}/result", status_code=status.HTTP_204_NO_CONTENT)
async def action_result(
    request_id: str, payload: dict[str, Any], _: CurrentUser
) -> None:
    ok = await bridge.submit_result(request_id, payload)
    if not ok:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "requête desktop introuvable ou expirée"
        )


# ---------------------------------------------------------------------------
# Macros desktop (CRUD + run on demand depuis l'UI)
# ---------------------------------------------------------------------------


class MacroIn(BaseModel):
    name: str
    description: str = ""
    steps: list[dict[str, Any]]


class MacroOut(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    steps: list[dict[str, Any]]
    created_at: str
    updated_at: str


def _to_out(m: DesktopMacro) -> MacroOut:
    return MacroOut(
        id=str(m.id),
        slug=m.slug,
        name=m.name,
        description=m.description,
        steps=m.steps_json,
        created_at=m.created_at.isoformat(),
        updated_at=m.updated_at.isoformat(),
    )


@router.get("/macros", response_model=list[MacroOut])
async def list_macros(user: CurrentUser, db: DbSession) -> list[MacroOut]:
    rows = (
        await db.execute(
            select(DesktopMacro)
            .where(DesktopMacro.user_id == user.id)
            .order_by(DesktopMacro.name)
        )
    ).scalars().all()
    return [_to_out(m) for m in rows]


@router.post("/macros", response_model=MacroOut)
async def create_macro(payload: MacroIn, user: CurrentUser, db: DbSession) -> MacroOut:
    cleaned, errors = builtin_tools.validate_steps(payload.steps)
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"errors": errors})
    slug = builtin_tools.slugify(payload.name)
    existing = await db.scalar(
        select(DesktopMacro).where(
            DesktopMacro.user_id == user.id, DesktopMacro.slug == slug
        )
    )
    if existing is not None:
        existing.name = payload.name
        existing.description = payload.description
        existing.steps_json = cleaned
        m = existing
    else:
        m = DesktopMacro(
            user_id=user.id,
            slug=slug,
            name=payload.name,
            description=payload.description,
            steps_json=cleaned,
        )
        db.add(m)
    await db.commit()
    await db.refresh(m)
    return _to_out(m)


@router.patch("/macros/{macro_id}", response_model=MacroOut)
async def patch_macro(
    macro_id: UUID, payload: MacroIn, user: CurrentUser, db: DbSession
) -> MacroOut:
    m = await db.get(DesktopMacro, macro_id)
    if m is None or m.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "macro introuvable")
    cleaned, errors = builtin_tools.validate_steps(payload.steps)
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"errors": errors})
    m.name = payload.name
    m.description = payload.description
    m.steps_json = cleaned
    await db.commit()
    await db.refresh(m)
    return _to_out(m)


@router.delete("/macros/{macro_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_macro(macro_id: UUID, user: CurrentUser, db: DbSession) -> None:
    m = await db.get(DesktopMacro, macro_id)
    if m is None or m.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "macro introuvable")
    await db.delete(m)
    await db.commit()


@router.post("/macros/{macro_id}/run")
async def run_macro(macro_id: UUID, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Exécute une macro à la demande (bouton « lancer » de l'UI)."""
    m = await db.get(DesktopMacro, macro_id)
    if m is None or m.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "macro introuvable")
    if not await registry.is_connected(user.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "aucun client desktop (app Windows) connecté"
        )
    results = await builtin_tools.run_macro_steps(user.id, m.steps_json)
    ok = all(r["result"].get("status") in ("ok", "shown") for r in results)
    return {"status": "ok" if ok else "partial", "macro": m.name, "steps": results}
