"""Routes nodes : registry, heartbeat depuis les agents."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.core.logging import get_logger
from spouet.db.models import Model, Node
from spouet.nodes.client import DIRECT_AGENT_MARKER
from spouet.nodes.client import probe as probe_ollama
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
    port: int = Field(default=8080, ge=1, le=65535)
    agent_port: int | None = Field(default=None, ge=1, le=65535)
    agent_version: str
    gpu_model: str | None = None
    vram_total_mb: int | None = Field(default=None, ge=0)
    vram_used_mb: int | None = Field(default=None, ge=0)
    ram_total_mb: int | None = Field(default=None, ge=0)
    ram_used_mb: int | None = Field(default=None, ge=0)
    disk_total_mb: int | None = Field(default=None, ge=0)
    disk_used_mb: int | None = Field(default=None, ge=0)
    llama_running: bool | None = None
    llama_model_loaded: str | None = None
    llama_n_ctx: int | None = None
    llama_n_gpu_layers: int | None = None
    llama_tps: float | None = None
    llama_slots_active: int | None = None
    llama_prompt_tokens_processed: int | None = None
    llama_tokens_generated: int | None = None
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
    agent_port: int | None
    status: str
    last_seen: datetime | None
    vram_total_mb: int | None
    vram_used_mb: int | None
    gpu_model: str | None
    ram_total_mb: int | None
    ram_used_mb: int | None
    disk_total_mb: int | None
    disk_used_mb: int | None
    agent_version: str | None
    tags: list[str]
    models: list[ModelOut]
    # Champs llama.cpp
    llama_running: bool | None
    llama_model_loaded: str | None
    llama_n_ctx: int | None
    llama_n_gpu_layers: int | None
    llama_tps: float | None
    llama_slots_active: int | None
    llama_prompt_tokens_processed: int | None
    llama_tokens_generated: int | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(payload: HeartbeatRequest, _: CurrentUser, db: DbSession) -> HeartbeatResponse:
    """Reçoit un heartbeat d'un node-agent. Upsert node + models."""
    from spouet.core.config import settings

    now = datetime.now(UTC)
    node = await db.scalar(select(Node).where(Node.name == payload.name))
    if node is None:
        node = Node(name=payload.name, host=payload.host, port=payload.port)
        db.add(node)

    node.host = payload.host
    node.port = payload.port
    node.agent_port = payload.agent_port
    node.status = "online"
    node.last_seen = now
    node.vram_total_mb = payload.vram_total_mb
    node.vram_used_mb = payload.vram_used_mb
    node.gpu_model = payload.gpu_model
    node.ram_total_mb = payload.ram_total_mb
    node.ram_used_mb = payload.ram_used_mb
    node.disk_total_mb = payload.disk_total_mb
    node.disk_used_mb = payload.disk_used_mb
    node.agent_version = payload.agent_version
    node.tags = payload.tags
    node.llama_running = payload.llama_running
    node.llama_model_loaded = payload.llama_model_loaded
    node.llama_n_ctx = payload.llama_n_ctx
    node.llama_n_gpu_layers = payload.llama_n_gpu_layers
    node.llama_tps = payload.llama_tps
    node.llama_slots_active = payload.llama_slots_active
    node.llama_prompt_tokens_processed = payload.llama_prompt_tokens_processed
    node.llama_tokens_generated = payload.llama_tokens_generated

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


class NodeCreate(BaseModel):
    """Création manuelle d'un node Ollama (sans node-agent installé sur la machine cible).

    Le backend interrogera périodiquement `http://{host}:{port}/api/tags` pour
    rafraîchir la liste des modèles et le statut online/offline.
    """

    name: str = Field(min_length=1, max_length=120)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=11434, ge=1, le=65535)
    tags: list[str] = Field(default_factory=list)


class NodeProbeOut(BaseModel):
    reachable: bool
    error: str | None
    models: list[str]


@router.post("/probe", response_model=NodeProbeOut)
async def probe_node(payload: NodeCreate, _: CurrentUser) -> NodeProbeOut:
    """Teste la connectivité d'un Ollama sans le persister. Utile pour valider la config UI."""
    result = await probe_ollama(f"http://{payload.host}:{payload.port}")
    return NodeProbeOut(
        reachable=result.reachable,
        error=result.error,
        models=[m.name for m in result.models],
    )


@router.post("", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
async def create_node(payload: NodeCreate, _: CurrentUser, db: DbSession) -> NodeOut:
    """Enregistre un Ollama joignable directement (sans node-agent).

    Le node sera marqué `online` immédiatement si le probe réussit, puis
    rafraîchi périodiquement par la tâche Celery `poll_direct_nodes`.
    """
    existing = await db.scalar(select(Node).where(Node.name == payload.name))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Node '{payload.name}' existe déjà")

    result = await probe_ollama(f"http://{payload.host}:{payload.port}")
    now = datetime.now(UTC)

    node = Node(
        name=payload.name,
        host=payload.host,
        port=payload.port,
        agent_version=DIRECT_AGENT_MARKER,
        tags=payload.tags,
        status="online" if result.reachable else "offline",
        last_seen=now if result.reachable else None,
    )
    db.add(node)
    await db.flush()

    if result.reachable:
        for m in result.models:
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
    await db.commit()
    await db.refresh(node)
    logger.info(
        "node.created_direct",
        name=node.name,
        reachable=result.reachable,
        models=len(result.models),
    )

    models = await _models_for_node(db, node.id)
    return _node_out(node, models)


@router.get("", response_model=list[NodeOut])
async def list_nodes(_: CurrentUser, db: DbSession) -> list[NodeOut]:
    rows = (await db.execute(select(Node))).scalars().all()
    out: list[NodeOut] = []
    for n in rows:
        models = await _models_for_node(db, n.id)
        out.append(_node_out(n, models))
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


# ---------------------------------------------------------------------------
# Routes proxy → agent API (llama.cpp management)
# ---------------------------------------------------------------------------

async def _agent_url(db: DbSession, node_id: UUID) -> tuple[Node, str]:
    """Retourne le node + l'URL de base de son agent API."""
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    if node.agent_port is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Node does not have an agent port — install spouet-agent ≥ 0.2.0"
        )
    return node, f"http://{node.host}:{node.agent_port}"


def _raise_agent_unreachable(base: str, exc: Exception) -> None:
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        f"Agent injoignable ({base}). "
        f"Relance spouet-agent avec --host <ip-routable-depuis-le-backend>. "
        f"Détail : {exc}",
    )


@router.get("/{node_id}/llama-config")
async def get_llama_config(node_id: UUID, _: CurrentUser, db: DbSession) -> dict:  # type: ignore[type-arg]
    """Retourne la config llama.cpp actuelle du node."""
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    return {
        "llama_n_ctx": node.llama_n_ctx,
        "llama_n_gpu_layers": node.llama_n_gpu_layers,
        "llama_running": node.llama_running,
        "llama_model_loaded": node.llama_model_loaded,
        "llama_tps": node.llama_tps,
        "llama_slots_active": node.llama_slots_active,
    }


class LlamaConfigPatch(BaseModel):
    n_ctx: int | None = None
    n_gpu_layers: int | None = None
    n_batch: int | None = None
    n_ubatch: int | None = None
    n_threads: int | None = None
    n_parallel: int | None = None


@router.patch("/{node_id}/llama-config")
async def patch_llama_config(
    node_id: UUID, payload: LlamaConfigPatch, _: CurrentUser, db: DbSession
) -> dict:  # type: ignore[type-arg]
    """Change les paramètres llama.cpp du node (redémarre llama-server)."""
    node, base = await _agent_url(db, node_id)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.patch(f"{base}/config", json=payload.model_dump(exclude_none=True))
            if r.status_code >= 400:
                raise HTTPException(r.status_code, r.text)
            return r.json()
    except httpx.ConnectError as exc:
        _raise_agent_unreachable(base, exc)


@router.get("/{node_id}/local-models")
async def get_local_models(node_id: UUID, _: CurrentUser, db: DbSession) -> list[dict]:  # type: ignore[type-arg]
    """Liste les modèles GGUF disponibles sur le node."""
    _, base = await _agent_url(db, node_id)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{base}/models")
            if r.status_code >= 400:
                raise HTTPException(r.status_code, r.text)
            return r.json()
    except httpx.ConnectError as exc:
        _raise_agent_unreachable(base, exc)


class ModelPullRequest(BaseModel):
    hf_repo: str
    filename: str
    hf_token: str | None = None


@router.post("/{node_id}/local-models/pull", status_code=status.HTTP_202_ACCEPTED)
async def pull_model(
    node_id: UUID, payload: ModelPullRequest, _: CurrentUser, db: DbSession
) -> dict:  # type: ignore[type-arg]
    """Démarre le téléchargement d'un modèle GGUF sur le node."""
    _, base = await _agent_url(db, node_id)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{base}/models/download", json=payload.model_dump())
            if r.status_code >= 400:
                raise HTTPException(r.status_code, r.text)
            return r.json()
    except httpx.ConnectError as exc:
        _raise_agent_unreachable(base, exc)


@router.get("/{node_id}/local-models/pull/status")
async def pull_status(node_id: UUID, _: CurrentUser, db: DbSession) -> dict:  # type: ignore[type-arg]
    """Progrès du dernier téléchargement."""
    _, base = await _agent_url(db, node_id)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{base}/models/download/status")
            if r.status_code >= 400:
                raise HTTPException(r.status_code, r.text)
            return r.json()
    except httpx.ConnectError as exc:
        _raise_agent_unreachable(base, exc)


class ModelLoadRequest(BaseModel):
    filename: str


@router.post("/{node_id}/local-models/load")
async def load_model(
    node_id: UUID, payload: ModelLoadRequest, _: CurrentUser, db: DbSession
) -> dict:  # type: ignore[type-arg]
    """Change le modèle actif sur le node."""
    _, base = await _agent_url(db, node_id)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{base}/models/load", json=payload.model_dump())
            if r.status_code >= 400:
                raise HTTPException(r.status_code, r.text)
            return r.json()
    except httpx.ConnectError as exc:
        _raise_agent_unreachable(base, exc)


@router.delete("/{node_id}/local-models/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_local_model(
    node_id: UUID, filename: str, _: CurrentUser, db: DbSession
) -> None:
    _, base = await _agent_url(db, node_id)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.delete(f"{base}/models/{filename}")
            if r.status_code >= 400:
                raise HTTPException(r.status_code, r.text)
    except httpx.ConnectError as exc:
        _raise_agent_unreachable(base, exc)


async def _models_for_node(db, node_id: UUID) -> list[Model]:  # type: ignore[no-untyped-def]
    return list((await db.execute(select(Model).where(Model.node_id == node_id))).scalars().all())


def _node_out(n: Node, models: list[Model]) -> NodeOut:
    return NodeOut(
        id=str(n.id),
        name=n.name,
        host=n.host,
        port=n.port,
        agent_port=n.agent_port,
        status="online" if n.is_online() else "offline",
        last_seen=n.last_seen,
        vram_total_mb=n.vram_total_mb,
        vram_used_mb=n.vram_used_mb,
        gpu_model=n.gpu_model,
        ram_total_mb=n.ram_total_mb,
        ram_used_mb=n.ram_used_mb,
        disk_total_mb=n.disk_total_mb,
        disk_used_mb=n.disk_used_mb,
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
        llama_running=n.llama_running,
        llama_model_loaded=n.llama_model_loaded,
        llama_n_ctx=n.llama_n_ctx,
        llama_n_gpu_layers=n.llama_n_gpu_layers,
        llama_tps=n.llama_tps,
        llama_slots_active=n.llama_slots_active,
        llama_prompt_tokens_processed=n.llama_prompt_tokens_processed,
        llama_tokens_generated=n.llama_tokens_generated,
    )
