"""Routes REST pour les connectors persistants.

Cycle de vie côté API : install (depuis manifest path serveur ou push manifest),
configure (config_json validé contre config_schema), start, stop, list,
inspect routes, voir logs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.connectors import manager
from spouet.connectors.manifest import (
    ConnectorManifest,
    load_connector_manifest,
    validate_config,
)
from spouet.core.security import generate_token, hash_token
from spouet.db.models import Connector, ConnectorRoute
from spouet.tools.manifest import ManifestError

router = APIRouter()


class ConnectorOut(BaseModel):
    id: str
    slug: str
    name: str
    version: str
    description: str
    image: str
    enabled: bool
    status: str
    container_id: str | None
    last_error: str | None
    inbound_kinds: list[str]
    outbound_kinds: list[str]
    secrets_required: dict[str, str]
    config_schema: dict[str, Any]
    config: dict[str, Any]


class ConnectorInstallIn(BaseModel):
    path: str = Field(min_length=1, description="Chemin serveur du dossier connector")


class ConnectorPatch(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class ConnectorRouteOut(BaseModel):
    id: str
    external_id: str
    conversation_id: str
    metadata: dict[str, Any]
    created_at: str
    last_seen_at: str | None


class ConnectorStartOut(BaseModel):
    state: str
    container_id: str | None
    error: str | None


# ---------------------------------------------------------------------------
# Listing & install
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ConnectorOut])
async def list_connectors(_: CurrentUser, db: DbSession) -> list[ConnectorOut]:
    rows = (await db.execute(select(Connector).order_by(Connector.slug))).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("/install", response_model=ConnectorOut)
async def install_connector(
    payload: ConnectorInstallIn, user: CurrentUser, db: DbSession
) -> ConnectorOut:
    try:
        manifest = load_connector_manifest(Path(payload.path))
    except ManifestError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    existing = await db.scalar(select(Connector).where(Connector.slug == manifest.slug))
    raw_token = generate_token()
    hashed = hash_token(raw_token)
    if existing is None:
        row = Connector(
            user_id=user.id,
            slug=manifest.slug,
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            image=manifest.image,
            manifest_json=manifest.raw,
            config_json={},
            auth_token_hash=hashed,
        )
        db.add(row)
    else:
        existing.name = manifest.name
        existing.version = manifest.version
        existing.description = manifest.description
        existing.image = manifest.image
        existing.manifest_json = manifest.raw
        existing.auth_token_hash = hashed
        row = existing
    await db.commit()
    await db.refresh(row)
    out = _to_out(row)
    # Le token clair n'est exposé qu'à l'install (on le passera au container)
    return out


@router.patch("/{connector_id}", response_model=ConnectorOut)
async def patch_connector(
    connector_id: UUID, payload: ConnectorPatch, _: CurrentUser, db: DbSession
) -> ConnectorOut:
    row = await db.get(Connector, connector_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connector not found")
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.config is not None:
        manifest = _load_manifest_from_row(row)
        errs = validate_config(manifest, payload.config)
        if errs:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, {"config_errors": errs}
            )
        row.config_json = payload.config
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(connector_id: UUID, _: CurrentUser, db: DbSession) -> None:
    row = await db.get(Connector, connector_id)
    if row is None:
        return
    await manager.stop(db, row)
    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@router.post("/{connector_id}/start", response_model=ConnectorStartOut)
async def start_connector(
    connector_id: UUID, _: CurrentUser, db: DbSession
) -> ConnectorStartOut:
    row = await db.get(Connector, connector_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connector not found")
    raw_token = generate_token()
    row.auth_token_hash = hash_token(raw_token)
    await db.commit()
    res = await manager.start(db, row, raw_token=raw_token)
    return ConnectorStartOut(
        state=res.state, container_id=res.container_id, error=res.error
    )


@router.post("/{connector_id}/stop", response_model=ConnectorStartOut)
async def stop_connector(
    connector_id: UUID, _: CurrentUser, db: DbSession
) -> ConnectorStartOut:
    row = await db.get(Connector, connector_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connector not found")
    res = await manager.stop(db, row)
    return ConnectorStartOut(
        state=res.state, container_id=res.container_id, error=res.error
    )


@router.post("/{connector_id}/refresh", response_model=ConnectorStartOut)
async def refresh_connector(
    connector_id: UUID, _: CurrentUser, db: DbSession
) -> ConnectorStartOut:
    row = await db.get(Connector, connector_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connector not found")
    res = await manager.refresh_status(db, row)
    return ConnectorStartOut(
        state=res.state, container_id=res.container_id, error=res.error
    )


@router.get("/{connector_id}/logs")
async def connector_logs(
    connector_id: UUID, _: CurrentUser, db: DbSession, tail: int = 200
) -> dict[str, str]:
    row = await db.get(Connector, connector_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connector not found")
    return {"logs": await manager.logs(row, tail=tail)}


@router.get("/{connector_id}/routes", response_model=list[ConnectorRouteOut])
async def connector_routes(
    connector_id: UUID, _: CurrentUser, db: DbSession
) -> list[ConnectorRouteOut]:
    row = await db.get(Connector, connector_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connector not found")
    routes = (
        await db.execute(
            select(ConnectorRoute)
            .where(ConnectorRoute.connector_id == row.id)
            .order_by(ConnectorRoute.created_at.desc())
        )
    ).scalars().all()
    return [
        ConnectorRouteOut(
            id=str(r.id),
            external_id=r.external_id,
            conversation_id=str(r.conversation_id),
            metadata=r.metadata_json,
            created_at=r.created_at.isoformat(),
            last_seen_at=r.last_seen_at.isoformat() if r.last_seen_at else None,
        )
        for r in routes
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_manifest_from_row(row: Connector) -> ConnectorManifest:
    raw = row.manifest_json or {}
    return ConnectorManifest(
        slug=raw.get("slug", row.slug),
        name=raw.get("name", row.name),
        version=raw.get("version", row.version),
        image=raw.get("image", row.image),
        description=raw.get("description", row.description),
        network=raw.get("network", "bridge"),
        mem_limit=raw.get("mem_limit", "384m"),
        cpu_limit=float(raw.get("cpu_limit", 0.5)),
        secrets=dict(raw.get("secrets") or {}),
        config_schema=raw.get("config_schema") or {"type": "object"},
        inbound_kinds=list(raw.get("inbound_kinds") or ["message"]),
        outbound_kinds=list(raw.get("outbound_kinds") or ["send_message"]),
        raw=raw,
    )


def _to_out(row: Connector) -> ConnectorOut:
    raw = row.manifest_json or {}
    return ConnectorOut(
        id=str(row.id),
        slug=row.slug,
        name=row.name,
        version=row.version,
        description=row.description,
        image=row.image,
        enabled=row.enabled,
        status=row.status,
        container_id=row.container_id,
        last_error=row.last_error,
        inbound_kinds=list(raw.get("inbound_kinds") or ["message"]),
        outbound_kinds=list(raw.get("outbound_kinds") or ["send_message"]),
        secrets_required=dict(raw.get("secrets") or {}),
        config_schema=raw.get("config_schema") or {"type": "object"},
        config=row.config_json or {},
    )
