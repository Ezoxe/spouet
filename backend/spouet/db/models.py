"""Modèles SQLAlchemy 2 pour Spouet."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from spouet.core.config import settings
from spouet.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Users / Auth
# ---------------------------------------------------------------------------


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    api_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    token_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    default_model: Mapped[str | None] = mapped_column(String(255), nullable=True)


# ---------------------------------------------------------------------------
# Nodes Ollama
# ---------------------------------------------------------------------------


class Node(Base, TimestampMixin):
    __tablename__ = "nodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=11434, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="offline", nullable=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vram_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vram_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disk_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disk_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    agent_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    # Champs llama.cpp (remontés par heartbeat)
    llama_running: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    llama_model_loaded: Mapped[str | None] = mapped_column(String(255), nullable=True)
    llama_n_ctx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llama_n_gpu_layers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llama_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    llama_slots_active: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llama_prompt_tokens_processed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llama_tokens_generated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # NodeCapabilities sérialisé (compute_class, gpu_kind, llama_variant, warnings…)
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Génération d'images sur le node (extra spouet-agent[images]). Le backend
    # route les demandes d'image vers http://{host}:{image_port}/generate.
    image_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_model: Mapped[str | None] = mapped_column(String(255), nullable=True)

    models: Mapped[list[Model]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )

    def is_online(self) -> bool:
        if self.last_seen is None:
            return False
        delta = (_utcnow() - self.last_seen).total_seconds()
        return delta < settings.node_offline_after_s


class Model(Base, TimestampMixin):
    __tablename__ = "models"
    __table_args__ = (UniqueConstraint("node_id", "name", name="uq_model_node_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    quant: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parameter_size: Mapped[str | None] = mapped_column(String(32), nullable=True)
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    node: Mapped[Node] = relationship(back_populates="models")


# ---------------------------------------------------------------------------
# Workspaces multi-agents
# ---------------------------------------------------------------------------


class WorkspaceSession(Base, TimestampMixin):
    __tablename__ = "workspace_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), default="New workspace", nullable=False)

    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="workspace",
        cascade="all, delete-orphan",
        foreign_keys="[Conversation.workspace_id]",
    )


# ---------------------------------------------------------------------------
# Conversations / Messages
# ---------------------------------------------------------------------------


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), default="New conversation", nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_pref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    workspace_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    allowed_tool_slugs: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False
    )
    # Mots-clés générés automatiquement (et/ou édités) pour filtrer les
    # conversations. Enrichis au fil de l'échange par l'autoname LLM.
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, nullable=False, server_default="{}"
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    workspace: Mapped["WorkspaceSession | None"] = relationship(
        "WorkspaceSession",
        back_populates="conversations",
        foreign_keys=[workspace_id],
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user/assistant/tool/system
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True
    )
    model_used: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Time-to-first-token : délai entre l'envoi du prompt et le premier chunk
    # de contenu reçu. Mesure la latence "perçue" par l'utilisateur, distinct
    # de `latency_ms` qui mesure la durée totale du stream.
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class Tool(Base, TimestampMixin):
    __tablename__ = "tools"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image: Mapped[str] = mapped_column(String(255), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    network_mode: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    timeout_s: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ToolExecution(Base):
    __tablename__ = "tool_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False
    )
    args_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    stdout: Mapped[str] = mapped_column(Text, default="", nullable=False)
    stderr: Mapped[str] = mapped_column(Text, default="", nullable=False)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Macros desktop (séquences d'actions apprises, exécutées côté client Tauri)
# ---------------------------------------------------------------------------


class DesktopMacro(Base, TimestampMixin):
    """Séquence d'actions bureau nommée, apprise par la conversation.

    Ex. « soirée Minecraft » = [lancer CurseForge sur l'écran 1, ouvrir YouTube
    sur l'écran 2]. Exécutée côté client (app Tauri) via le pont desktop, jamais
    dans un conteneur Docker. Validée par l'utilisateur à la création (HITL),
    puis considérée de confiance pour les exécutions suivantes.
    """

    __tablename__ = "desktop_macros"
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_macro_user_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Liste d'étapes primitives, ex :
    #   [{"action": "launch_app", "app": "CurseForge", "monitor": 1, "mode": "fullscreen"},
    #    {"action": "open_url", "url": "https://youtube.com", "monitor": 2}]
    steps_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)


# ---------------------------------------------------------------------------
# Images générées
# ---------------------------------------------------------------------------


class GeneratedImage(Base, TimestampMixin):
    """Image produite par le microservice image-engine (diffusers).

    Les octets PNG sont stockés sur disque (volume `images_dir`) ; cette table ne
    garde que les métadonnées + le chemin relatif du fichier. Servie via
    l'endpoint authentifié /api/images/{id}/file. Optionnellement rattachée à une
    conversation (génération via le tool `generate_image`).
    """

    __tablename__ = "generated_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Chemin du fichier PNG *relatif* à images_dir (ex. "<uuid>.png").
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Paramètres de génération (steps, guidance, model, device…) pour rejouer/auditer.
    params_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class PromptTemplate(Base, TimestampMixin):
    """Modèle de prompt réutilisable, scopé par user."""

    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    shortcut: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ScheduledJob(Base, TimestampMixin):
    __tablename__ = "scheduled_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    cron: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    tools_allowed: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    model_pref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scheduled_jobs.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    output_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )


# ---------------------------------------------------------------------------
# RAG : Documents + Chunks
# ---------------------------------------------------------------------------


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="chunks")


# ---------------------------------------------------------------------------
# Memory long-terme
# ---------------------------------------------------------------------------


class Memory(Base, TimestampMixin):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )
    score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # pinned : injecté systématiquement dans le system prompt (issu de l'onboarding
    # — identité IA, prénom user, totem). Les non-pinned passent par recall sémantique.
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Coffre de secrets chiffrés
# ---------------------------------------------------------------------------


class Secret(Base, TimestampMixin):
    """Secret chiffré (Fernet). `value_encrypted` est un token base64."""

    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_secret_scope_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    scope: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    value_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)


# ---------------------------------------------------------------------------
# Connectors persistants (Discord, Telegram, IMAP, Matrix, MQTT, …)
# ---------------------------------------------------------------------------


class Connector(Base, TimestampMixin):
    __tablename__ = "connectors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image: Mapped[str] = mapped_column(String(255), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="stopped", nullable=False)
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    auth_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Metadata calculées dynamiquement (bot_user_id Discord, invite_url, etc.).
    # Différent de config_json qui contient la config user (persona, channels…).
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    routes: Mapped[list[ConnectorRoute]] = relationship(
        back_populates="connector", cascade="all, delete-orphan"
    )


class ConnectorRoute(Base):
    """Mapping (connector, identifiant externe) → conversation Spouet.

    Ex Discord : external_id = `channel:123456789` ou `dm:user-id`.
    """

    __tablename__ = "connector_routes"
    __table_args__ = (
        UniqueConstraint("connector_id", "external_id", name="uq_route_connector_external"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    connector: Mapped[Connector] = relationship(back_populates="routes")


# ---------------------------------------------------------------------------
# Mail (boîtes IMAP/SMTP, tri IA, réponses validées en HITL)
# ---------------------------------------------------------------------------


class MailAccount(Base, TimestampMixin):
    """Une boîte mail connectée (IMAP en lecture, SMTP en envoi).

    Le mot de passe n'est jamais stocké ici : il vit chiffré dans le coffre
    (scope `mail:<account_id>`, key `password`).
    """

    __tablename__ = "mail_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    imap_host: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, default=993, nullable=False)
    imap_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, default=465, nullable=False)
    smtp_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    username: Mapped[str] = mapped_column(String(320), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Comportement automatique
    auto_classify: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Déplacer les spams détectés vers `spam_folder` (réversible, jamais de suppression).
    auto_trash_spam: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    spam_folder: Mapped[str] = mapped_column(String(120), default="Junk", nullable=False)
    # Préparer automatiquement un brouillon de réponse (validation requise avant envoi).
    auto_draft_replies: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    signature: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Suivi de synchro
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_uid: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    messages: Mapped[list[MailMessage]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class MailMessage(Base):
    """Un mail récupéré et analysé."""

    __tablename__ = "mail_messages"
    __table_args__ = (
        UniqueConstraint("account_id", "folder", "uid", name="uq_mail_account_folder_uid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mail_accounts.id", ondelete="CASCADE"), nullable=False
    )
    uid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    folder: Mapped[str] = mapped_column(String(120), default="INBOX", nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    from_addr: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    from_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    to_addrs: Mapped[str] = mapped_column(Text, default="", nullable=False)
    subject: Mapped[str] = mapped_column(Text, default="", nullable=False)
    snippet: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Analyse IA
    classification: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    importance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    needs_reply: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # none | trashed (déplacé vers spam_folder)
    action_taken: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )

    account: Mapped[MailAccount] = relationship(back_populates="messages")


class MailDraft(Base, TimestampMixin):
    """Brouillon de réponse généré par l'IA, en attente de validation HITL.

    Aucun mail n'est jamais envoyé sans passer par `status='approved'` via une
    action explicite de l'utilisateur.
    """

    __tablename__ = "mail_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mail_accounts.id", ondelete="CASCADE"), nullable=False
    )
    # Mail auquel on répond (None = nouveau message).
    in_reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mail_messages.id", ondelete="SET NULL"), nullable=True
    )
    to_addrs: Mapped[str] = mapped_column(Text, default="", nullable=False)
    subject: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # pending | sent | rejected | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False, index=True
    )


# ---------------------------------------------------------------------------
# Timeseries de métriques nodes (tables partitionnées par jour, BRIN sur time)
# ---------------------------------------------------------------------------


class NodeMetricRaw(Base):
    """Snapshot brute par heartbeat (~10s). Rétention 24h (purge worker)."""

    __tablename__ = "node_metrics_raw"

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    cpu_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    ram_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vram_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vram_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disk_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    net_rx_kbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_tx_kbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    llama_running: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    llama_model_loaded: Mapped[str | None] = mapped_column(Text, nullable=True)
    llama_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    llama_slots_active: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llama_prompt_tokens_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    llama_gen_tokens_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    llama_queue_pending: Mapped[int | None] = mapped_column(Integer, nullable=True)


class NodeMetric1Min(Base):
    """Agrégat tumbling 1-minute. Rétention 7j (configurable)."""

    __tablename__ = "node_metrics_1min"

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    cpu_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    ram_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vram_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vram_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disk_used_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    net_rx_kbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_tx_kbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    llama_running: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    llama_model_loaded: Mapped[str | None] = mapped_column(Text, nullable=True)
    llama_tps: Mapped[float | None] = mapped_column(Float, nullable=True)
    llama_slots_active: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llama_prompt_tokens_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    llama_gen_tokens_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    llama_queue_pending: Mapped[int | None] = mapped_column(Integer, nullable=True)
