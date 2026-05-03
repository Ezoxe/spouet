"""Routes nodes : registry, heartbeat depuis les agents."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.core.logging import get_logger
from spouet.db.models import Model, Node
from spouet.nodes.router import list_available_models

router = APIRouter()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Schémas
# ---------------------------------------------------------------------------


class HeartbeatModel(BaseModel):
    name: str
    digest: str | None = None
    size_bytes: int | None = None
    quant: str | None = None
    parameter_size: str | None = None
    supports_tools: bool = False


class HeartbeatRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=11434, ge=1, le=65535)
    agent_version: str
    gpu_model: str | None = None
    vram_total_mb: int | None = Field(default=None, ge=0)
    vram_used_mb: int | None = Field(default=None, ge=0)
    tags: list[str] = Field(default_factory=list)
    models: list[HeartbeatModel] = Field(default_factory=list)


class HeartbeatResponse(BaseModel):
    node_id: str
    next_heartbeat_in_s: int


class ModelOut(BaseModel):
    name: str
    digest: str | None
    size_bytes: int | None
    parameter_size: str | None
    supports_tools: bool


class NodeOut(BaseModel):
    id: str
    name: str
    host: str
    port: int
    status: str
    last_seen: datetime | None
    vram_total_mb: int | None
    vram_used_mb: int | None
    gpu_model: str | None
    agent_version: str | None
    tags: list[str]
    models: list[ModelOut]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(payload: HeartbeatRequest, _: CurrentUser, db: DbSession) -> HeartbeatResponse:
    """Reçoit un heartbeat d'un node-agent. Upsert node + models."""
    from spouet.core.config import settings

    now = datetime.now(timezone.utc)
    node = await db.scalar(select(Node).where(Node.name == payload.name))
    if node is None:
        node = Node(name=payload.name, host=payload.host, port=payload.port)
        db.add(node)

    node.host = payload.host
    node.port = payload.port
    node.status = "online"
    node.last_seen = now
    node.vram_total_mb = payload.vram_total_mb
    node.vram_used_mb = payload.vram_used_mb
    node.gpu_model = payload.gpu_model
    node.agent_version = payload.agent_version
    node.tags = payload.tags

    await db.flush()  # garantit node.id

    # Upsert des models : marque ceux présents, supprime ceux absents
    existing = {m.name: m for m in await _models_for_node(db, node.id)}
    seen_names = set()
    for m in payload.models:
        seen_names.add(m.name)
        if m.name in existing:
            row = existing[m.name]
            row.digest = m.digest
            row.size_bytes = m.size_bytes
            row.quant = m.quant
            row.parameter_size = m.parameter_size
            row.supports_tools = m.supports_tools
            row.last_seen = now
        else:
            db.add(
                Model(
                    node_id=node.id,
                    name=m.name,
                    digest=m.digest,
                    size_bytes=m.size_bytes,
                    quant=m.quant,
                    parameter_size=m.parameter_size,
                    supports_tools=m.supports_tools,
                    last_seen=now,
                )
            )
    for name, row in existing.items():
        if name not in seen_names:
            await db.delete(row)

    await db.commit()
    logger.info(
        "node.heartbeat",
        node=payload.name,
        models=len(payload.models),
        vram_used=payload.vram_used_mb,
    )
    return HeartbeatResponse(
        node_id=str(node.id), next_heartbeat_in_s=settings.node_heartbeat_interval_s
    )


@router.get("", response_model=list[NodeOut])
async def list_nodes(_: CurrentUser, db: DbSession) -> list[NodeOut]:
    rows = (await db.execute(select(Node))).scalars().all()
    out: list[NodeOut] = []
    for n in rows:
        models = await _models_for_node(db, n.id)
        out.append(
            NodeOut(
                id=str(n.id),
                name=n.name,
                host=n.host,
                port=n.port,
                status="online" if n.is_online() else "offline",
                last_seen=n.last_seen,
                vram_total_mb=n.vram_total_mb,
                vram_used_mb=n.vram_used_mb,
                gpu_model=n.gpu_model,
                agent_version=n.agent_version,
                tags=n.tags,
                models=[
                    ModelOut(
                        name=m.name,
                        digest=m.digest,
                        size_bytes=m.size_bytes,
                        parameter_size=m.parameter_size,
                        supports_tools=m.supports_tools,
                    )
                    for m in models
                ],
            )
        )
    return out


@router.get("/models", response_model=list[dict])  # type: ignore[type-arg]
async def list_models(_: CurrentUser, db: DbSession) -> list[dict]:  # type: ignore[type-arg]
    """Liste agrégée des modèles disponibles à travers tous les nodes online."""
    return await list_available_models(db)


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(node_id: UUID, _: CurrentUser, db: DbSession) -> None:
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    await db.delete(node)
    await db.commit()


async def _models_for_node(db, node_id: UUID) -> list[Model]:  # type: ignore[no-untyped-def]
    return list((await db.execute(select(Model).where(Model.node_id == node_id))).scalars().all())
