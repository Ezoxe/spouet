"""Routes nodes : registry, heartbeat depuis les agents."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta as _timedelta
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from spouet.api.deps import CurrentUser, DbSession
from spouet.core.logging import get_logger
from spouet.db.models import Model, Node, NodeMetric1Min, NodeMetricRaw
from spouet.images import client as image_client
from spouet.nodes.client import DIRECT_AGENT_MARKER
from spouet.nodes.client import probe as probe_ollama
from spouet.nodes.router import list_available_models
from spouet.realtime.hub import node_metrics_channel, publish

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
    # Capabilities calculées par node-agent.capabilities.probe_capabilities()
    capabilities: dict | None = None
    # Génération d'images (agents ≥ 0.3.0 avec extra [images])
    image_enabled: bool = False
    image_port: int | None = Field(default=None, ge=1, le=65535)
    image_model: str | None = None
    # Métriques système supplémentaires (agents ≥ 0.3.0)
    cpu_pct: float | None = Field(default=None, ge=0, le=100)
    net_rx_kbps: float | None = Field(default=None, ge=0)
    net_tx_kbps: float | None = Field(default=None, ge=0)
    llama_queue_pending: int | None = Field(default=None, ge=0)


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
    # Capabilities matérielles (issues du heartbeat de spouet-agent ≥ 0.3.0)
    capabilities: dict | None = None
    # Génération d'images sur ce node
    image_enabled: bool = False
    image_port: int | None = None
    image_model: str | None = None


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
    # Capabilities : envoyées par les agents ≥ 0.3.0. Anciennes versions → None
    # (rétro-compat : on ne touche pas la valeur précédente si payload absent).
    if payload.capabilities is not None:
        node.capabilities = payload.capabilities
    node.image_enabled = payload.image_enabled
    node.image_port = payload.image_port
    node.image_model = payload.image_model

    await db.flush()  # garantit node.id avant l'insert métrique

    # Persiste une ligne dans la timeseries node_metrics_raw — alimentation
    # du dashboard historique. La table est partitionnée par jour ; en cas
    # d'absence de partition pour `now`, le worker create_metrics_partitions
    # crée les partitions à venir ; en attendant, la partition DEFAULT catche.
    db.add(
        NodeMetricRaw(
            time=now,
            node_id=node.id,
            cpu_pct=payload.cpu_pct,
            ram_used_mb=payload.ram_used_mb,
            ram_total_mb=payload.ram_total_mb,
            vram_used_mb=payload.vram_used_mb,
            vram_total_mb=payload.vram_total_mb,
            disk_used_mb=payload.disk_used_mb,
            net_rx_kbps=payload.net_rx_kbps,
            net_tx_kbps=payload.net_tx_kbps,
            llama_running=payload.llama_running,
            llama_model_loaded=payload.llama_model_loaded,
            llama_tps=payload.llama_tps,
            llama_slots_active=payload.llama_slots_active,
            llama_prompt_tokens_total=payload.llama_prompt_tokens_processed,
            llama_gen_tokens_total=payload.llama_tokens_generated,
            llama_queue_pending=payload.llama_queue_pending,
        )
    )

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
    # Push live au dashboard via SSE (best-effort, ne bloque pas l'agent)
    await publish(
        node_metrics_channel(node.id),
        "heartbeat",
        {
            "time": now.isoformat(),
            "cpu_pct": payload.cpu_pct,
            "ram_used_mb": payload.ram_used_mb,
            "vram_used_mb": payload.vram_used_mb,
            "net_rx_kbps": payload.net_rx_kbps,
            "net_tx_kbps": payload.net_tx_kbps,
            "llama_running": payload.llama_running,
            "llama_model_loaded": payload.llama_model_loaded,
            "llama_tps": payload.llama_tps,
            "llama_slots_active": payload.llama_slots_active,
            "llama_prompt_tokens_total": payload.llama_prompt_tokens_processed,
            "llama_gen_tokens_total": payload.llama_tokens_generated,
            "llama_queue_pending": payload.llama_queue_pending,
        },
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
    # selectinload évite le N+1 : 1 SELECT nodes + 1 SELECT models groupé
    # au lieu de 1 + N (un SELECT par node pour récupérer ses modèles).
    rows = (
        await db.execute(select(Node).options(selectinload(Node.models)))
    ).scalars().all()
    return [_node_out(n, list(n.models)) for n in rows]


@router.get("/models", response_model=list[dict])  # type: ignore[type-arg]
async def list_models(_: CurrentUser, db: DbSession) -> list[dict]:  # type: ignore[type-arg]
    """Liste agrégée des modèles disponibles à travers tous les nodes online."""
    return await list_available_models(db)


@router.get("/{node_id}", response_model=NodeOut)
async def get_node(node_id: UUID, _: CurrentUser, db: DbSession) -> NodeOut:
    """Détail d'un node (utilisé pour les rafraîchissements live)."""
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    models = await _models_for_node(db, node.id)
    return _node_out(node, models)


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


@router.post("/{node_id}/local-models/check")
async def check_local_model(
    node_id: UUID, payload: ModelPullRequest, _: CurrentUser, db: DbSession
) -> dict:  # type: ignore[type-arg]
    """Pré-vérifie qu'un fichier GGUF est compatible llama.cpp avant de le télécharger."""
    _, base = await _agent_url(db, node_id)
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(f"{base}/models/check", json=payload.model_dump())
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


# ---------------------------------------------------------------------------
# Routes proxy → API image du node (génération d'images)
# ---------------------------------------------------------------------------

async def _image_url(db: DbSession, node_id: UUID) -> tuple[Node, str]:
    """Retourne le node + l'URL de base de son API image."""
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    if not node.image_enabled or node.image_port is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ce node n'expose pas la génération d'images "
            "(installer spouet-agent[images] sur une machine GPU).",
        )
    return node, f"http://{node.host}:{node.image_port}"


@router.get("/{node_id}/image/status")
async def image_status(node_id: UUID, _: CurrentUser, db: DbSession) -> dict:  # type: ignore[type-arg]
    """État du moteur d'images du node (modèle actif, device, pull/load)."""
    _, base = await _image_url(db, node_id)
    try:
        return await image_client.status(base)
    except image_client.ImageEngineError as exc:
        _raise_agent_unreachable(base, exc)


class ImagePullRequest(BaseModel):
    model: str = Field(min_length=1)
    hf_token: str | None = None


@router.post("/{node_id}/image/pull", status_code=status.HTTP_202_ACCEPTED)
async def image_pull(
    node_id: UUID, payload: ImagePullRequest, _: CurrentUser, db: DbSession
) -> dict:  # type: ignore[type-arg]
    """Démarre le téléchargement d'un modèle d'images sur le node."""
    _, base = await _image_url(db, node_id)
    try:
        return await image_client.pull(base, payload.model, payload.hf_token)
    except image_client.ImageEngineError as exc:
        _raise_agent_unreachable(base, exc)


@router.post("/{node_id}/image/pull/check")
async def image_pull_check(
    node_id: UUID, payload: ImagePullRequest, _: CurrentUser, db: DbSession
) -> dict:  # type: ignore[type-arg]
    """Pré-vérifie qu'un repo HF est chargeable par le moteur d'images (avant pull)."""
    _, base = await _image_url(db, node_id)
    try:
        return await image_client.pull_check(base, payload.model, payload.hf_token)
    except image_client.ImageEngineError as exc:
        _raise_agent_unreachable(base, exc)


@router.get("/{node_id}/image/pull/status")
async def image_pull_status(node_id: UUID, _: CurrentUser, db: DbSession) -> dict:  # type: ignore[type-arg]
    """Progrès du dernier téléchargement de modèle d'images."""
    _, base = await _image_url(db, node_id)
    try:
        return await image_client.pull_status(base)
    except image_client.ImageEngineError as exc:
        _raise_agent_unreachable(base, exc)


class ImageLoadRequest(BaseModel):
    model: str | None = None


@router.post("/{node_id}/image/load")
async def image_load(
    node_id: UUID, payload: ImageLoadRequest, _: CurrentUser, db: DbSession
) -> dict:  # type: ignore[type-arg]
    """Met un modèle d'images en mémoire sur le node (le rend actif)."""
    _, base = await _image_url(db, node_id)
    try:
        return await image_client.load(base, payload.model)
    except image_client.ImageEngineError as exc:
        _raise_agent_unreachable(base, exc)


@router.get("/{node_id}/image/models")
async def image_models(node_id: UUID, _: CurrentUser, db: DbSession) -> list[dict]:  # type: ignore[type-arg]
    """Modèles d'images téléchargés sur le node (cache HF)."""
    _, base = await _image_url(db, node_id)
    try:
        return await image_client.list_models(base)
    except image_client.ImageEngineError as exc:
        _raise_agent_unreachable(base, exc)


@router.post("/{node_id}/image/models/delete")
async def image_delete_model(
    node_id: UUID, payload: ImagePullRequest, _: CurrentUser, db: DbSession
) -> dict:  # type: ignore[type-arg]
    """Supprime un modèle d'images du node (libère l'espace disque)."""
    _, base = await _image_url(db, node_id)
    try:
        return await image_client.delete_model(base, payload.model)
    except image_client.ImageEngineError as exc:
        _raise_agent_unreachable(base, exc)


@router.get("/{node_id}/diag")
async def get_node_diag(node_id: UUID, _: CurrentUser, db: DbSession) -> dict:  # type: ignore[type-arg]
    """Agrège capabilities + 200 dernières lignes de log llama-server +
    last_startup_error + 3 derniers heartbeats. Format copier-coller pour
    un bug report.
    """
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")

    agent_diag: dict[str, Any] = {}
    if node.agent_port:
        base = f"http://{node.host}:{node.agent_port}"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{base}/diag/llama", params={"n": 200})
                if r.status_code == 200:
                    agent_diag = r.json()
        except httpx.HTTPError as e:
            agent_diag = {"error": f"agent unreachable: {e}"}

    recent_metrics = (
        await db.execute(
            select(NodeMetricRaw)
            .where(NodeMetricRaw.node_id == node_id)
            .order_by(NodeMetricRaw.time.desc())
            .limit(3)
        )
    ).scalars().all()

    return {
        "node": {
            "name": node.name,
            "host": node.host,
            "agent_version": node.agent_version,
            "status": "online" if node.is_online() else "offline",
            "last_seen": node.last_seen.isoformat() if node.last_seen else None,
        },
        "capabilities": node.capabilities,
        "agent_diag": agent_diag,
        "recent_heartbeats": [
            {
                "time": m.time.isoformat(),
                "cpu_pct": m.cpu_pct,
                "ram_used_mb": m.ram_used_mb,
                "vram_used_mb": m.vram_used_mb,
                "llama_running": m.llama_running,
                "llama_model_loaded": m.llama_model_loaded,
                "llama_tps": m.llama_tps,
            }
            for m in recent_metrics
        ],
    }


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


# ---------------------------------------------------------------------------
# Timeseries — endpoints lecture
# ---------------------------------------------------------------------------


_RANGE_TO_SECONDS = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 24 * 3600,
}


def _iso_utc(dt: datetime) -> str:
    """ISO 8601 explicitement en UTC avec suffixe 'Z'.

    Les timestamps sont stockés en UTC (`datetime.now(UTC)`). On garantit un
    instant non ambigu pour le client (sinon une datetime naïve serait
    interprétée en heure locale du navigateur → décalage de plusieurs heures).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


@router.get("/{node_id}/metrics")
async def get_node_metrics(
    node_id: UUID,
    _: CurrentUser,
    db: DbSession,
    range: str = "1h",
    limit: int = 1000,
) -> dict:  # type: ignore[type-arg]
    """Retourne la série temporelle d'un node sur la plage demandée.

    `range` : 1h, 6h, 24h, 7d. Au-delà de 24h, on lit dans node_metrics_1min
    (déjà downsamplée). Limité à 1000 points par défaut.
    """
    node = await db.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    seconds = _RANGE_TO_SECONDS.get(range)
    if seconds is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown range {range!r}")

    cutoff = datetime.now(UTC) - _timedelta(seconds)
    # raw pour les courtes fenêtres (<= 24h), 1min pour les plus longues
    model_cls = NodeMetricRaw if seconds <= _RANGE_TO_SECONDS["24h"] else NodeMetric1Min

    rows = (
        await db.execute(
            select(model_cls)
            .where(model_cls.node_id == node_id, model_cls.time >= cutoff)
            .order_by(model_cls.time.asc())
            .limit(limit)
        )
    ).scalars().all()
    return {
        "node_id": str(node_id),
        "range": range,
        "source": "raw" if model_cls is NodeMetricRaw else "1min",
        # Heure serveur : permet au client de calculer la fraîcheur des données
        # sans dépendre de l'horloge (potentiellement fausse) du navigateur.
        "now": _iso_utc(datetime.now(UTC)),
        "series": [
            {
                "time": _iso_utc(r.time),
                "cpu_pct": r.cpu_pct,
                "ram_used_mb": r.ram_used_mb,
                "vram_used_mb": r.vram_used_mb,
                "disk_used_mb": r.disk_used_mb,
                "net_rx_kbps": r.net_rx_kbps,
                "net_tx_kbps": r.net_tx_kbps,
                "llama_tps": r.llama_tps,
                "llama_slots_active": r.llama_slots_active,
                "llama_running": r.llama_running,
                "llama_model_loaded": r.llama_model_loaded,
                "llama_queue_pending": r.llama_queue_pending,
            }
            for r in rows
        ],
    }


@router.get("/metrics/aggregate")
async def get_cluster_aggregate(
    _: CurrentUser, db: DbSession, range: str = "24h"
) -> dict:  # type: ignore[type-arg]
    """Vue cluster : nodes online/total, somme TPS, total tokens générés."""
    seconds = _RANGE_TO_SECONDS.get(range)
    if seconds is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown range {range!r}")
    cutoff = datetime.now(UTC) - _timedelta(seconds)

    nodes_rows = (await db.execute(select(Node))).scalars().all()
    online = sum(1 for n in nodes_rows if n.is_online())
    total_current_tps = sum((n.llama_tps or 0.0) for n in nodes_rows if n.is_online())

    # Total tokens générés sur la fenêtre : pour chaque node, delta du compteur
    # cumulatif (MAX - MIN) sur la fenêtre, puis somme sur les nodes. Le GROUP BY
    # node_id est indispensable — sommer le compteur cumulatif de tous les nodes
    # à chaque point puis soustraire le minimum global (SUM - MIN) n'a aucun sens.
    src = NodeMetricRaw if seconds <= _RANGE_TO_SECONDS["24h"] else NodeMetric1Min
    per_node = (
        select(
            (
                func.max(src.llama_gen_tokens_total)
                - func.min(src.llama_gen_tokens_total)
            ).label("delta")
        )
        .where(src.time >= cutoff)
        .group_by(src.node_id)
        .subquery()
    )
    tokens_row = (
        await db.execute(select(func.coalesce(func.sum(per_node.c.delta), 0)))
    ).scalar()
    return {
        "range": range,
        "nodes_online": online,
        "nodes_total": len(nodes_rows),
        "total_tps_current": round(total_current_tps, 2),
        "total_tokens_generated_window": int(tokens_row or 0),
    }


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
        capabilities=n.capabilities,
        image_enabled=n.image_enabled,
        image_port=n.image_port,
        image_model=n.image_model,
    )
