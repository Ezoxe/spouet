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
from spouet.core.config import settings
from spouet.core.security import generate_token, hash_token
from spouet.db.models import Connector, ConnectorRoute
from spouet.realtime.hub import connector_outbound_channel, publish
from spouet.secrets import store as secrets_store
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
    metadata: dict[str, Any] = {}
    # URL OAuth d'invitation calculée à la volée si bot_user_id présent.
    invite_url: str | None = None


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
    meta = dict(row.metadata_json or {})
    invite_url: str | None = None
    if row.slug == "discord-bot" and meta.get("bot_user_id"):
        # permissions=274877942848 : View, Send Messages, Read Message History,
        # Add Reactions, Attach Files, Use External Emojis
        invite_url = (
            f"https://discord.com/oauth2/authorize?client_id={meta['bot_user_id']}"
            "&scope=bot+applications.commands&permissions=274877942848"
        )
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
        metadata=meta,
        invite_url=invite_url,
    )


# ---------------------------------------------------------------------------
# Wizard Discord (1-clic) + outbound bridge pour les tools
# ---------------------------------------------------------------------------


class DiscordQuickInstall(BaseModel):
    token: str = Field(min_length=20, description="Token bot Discord")
    bot_persona: str | None = None
    default_model: str | None = None
    allowed_channels: list[str] = Field(default_factory=list)
    respond_dm: bool = True
    trigger_prefix: str = ""


@router.post("/quick-install/discord", response_model=ConnectorOut)
async def quick_install_discord(
    payload: DiscordQuickInstall, user: CurrentUser, db: DbSession
) -> ConnectorOut:
    """Installation en 1 clic : crée le secret, charge le manifest serveur,
    upsert le connector et le démarre.

    Retourne le ConnectorOut avec invite_url qui se remplit dès que le bot
    répond au `on_ready` (event WS `bot_info`).
    """
    manifest_path = Path(settings.connectors_registry_dir) / "discord"
    try:
        manifest = load_connector_manifest(manifest_path)
    except ManifestError as e:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"manifest Discord introuvable côté serveur : {e}",
        ) from e

    # 1) Auto-création du secret connector:discord-bot/token
    await secrets_store.upsert(
        db,
        scope="connector:discord-bot",
        key="token",
        value=payload.token,
        description="Discord bot token (quick-install wizard)",
    )

    # 2) Config validée contre le config_schema du manifest
    config: dict[str, Any] = {
        "bot_persona": payload.bot_persona
        or "Tu es l'assistant Spouet. Tu réponds via Discord, en français, de manière concise.",
        "respond_dm": payload.respond_dm,
        "allowed_channels": payload.allowed_channels,
        "trigger_prefix": payload.trigger_prefix,
    }
    if payload.default_model:
        config["default_model"] = payload.default_model
    errs = validate_config(manifest, config)
    if errs:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, {"config_errors": errs}
        )

    # 3) Upsert connector row
    raw_token = generate_token()
    existing = await db.scalar(select(Connector).where(Connector.slug == manifest.slug))
    if existing is None:
        row = Connector(
            user_id=user.id,
            slug=manifest.slug,
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            image=manifest.image,
            manifest_json=manifest.raw,
            config_json=config,
            auth_token_hash=hash_token(raw_token),
            enabled=True,
        )
        db.add(row)
    else:
        existing.name = manifest.name
        existing.version = manifest.version
        existing.description = manifest.description
        existing.image = manifest.image
        existing.manifest_json = manifest.raw
        existing.config_json = config
        existing.auth_token_hash = hash_token(raw_token)
        existing.enabled = True
        row = existing
    await db.commit()
    await db.refresh(row)

    # 4) Démarre le container — le bot émettra `bot_info` après `on_ready`,
    # ce qui peuplera metadata.bot_user_id et donc l'invite_url.
    await manager.start(db, row, raw_token=raw_token)
    await db.refresh(row)
    return _to_out(row)


class OutboundIn(BaseModel):
    kind: str = Field(min_length=1, description="send_message, send_embed, react, typing…")
    external_id: str = Field(min_length=1)
    content: str | None = None
    content_json: dict[str, Any] | None = None
    reply_to: str | None = None
    message_id: str | None = None
    emoji: str | None = None


@router.post("/{slug}/outbound", status_code=status.HTTP_202_ACCEPTED)
async def push_outbound(
    slug: str, payload: OutboundIn, _: CurrentUser, db: DbSession
) -> dict:  # type: ignore[type-arg]
    """Publie un event outbound vers le container du connector.

    Utilisé par les tools `spouet-discord-*` pour envoyer des messages/embeds
    depuis une conversation Spouet vers Discord (ou tout autre connector).
    """
    row = await db.scalar(select(Connector).where(Connector.slug == slug))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"connector {slug!r} not found")
    if row.status != "running":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"connector {slug!r} not running (status={row.status})",
        )
    body: dict[str, Any] = {"kind": payload.kind, "external_id": payload.external_id}
    if payload.content is not None:
        body["content"] = payload.content
    if payload.content_json is not None:
        body["content_json"] = payload.content_json
    if payload.reply_to is not None:
        body["reply_to"] = payload.reply_to
    if payload.message_id is not None:
        body["message_id"] = payload.message_id
    if payload.emoji is not None:
        body["emoji"] = payload.emoji
    ok = await publish(connector_outbound_channel(row.id), payload.kind, body)
    return {"queued": ok, "connector_id": str(row.id)}
