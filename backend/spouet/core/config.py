"""Configuration centralisée (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPOUET_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Identité / sécurité
    secret_key: str = Field(min_length=32)
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=list)

    # Datastores
    database_url: PostgresDsn
    redis_url: RedisDsn

    # Ollama
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    # Tools sandbox
    tool_default_mem_limit: str = "256m"
    tool_default_cpu_limit: float = 1.0
    tool_default_timeout_s: int = 30

    # Connectors persistants
    connector_docker_network: str = "spouet_default"
    connector_backend_url: str = "ws://backend:8000"

    # Nodes
    node_offline_after_s: int = 30
    node_heartbeat_interval_s: int = 10

    # API
    api_token_bytes: int = 32
    rate_limit_per_minute: int = 60
    upload_max_bytes: int = 50 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
