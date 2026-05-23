"""Configuration centralisée (pydantic-settings)."""

from __future__ import annotations

import math
from collections import Counter
from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Patterns évidents qu'on refuse même s'ils font ≥ 32 chars — éviter qu'un
# admin mette `changeme___changeme___changeme___` en prod.
_FORBIDDEN_SECRET_PATTERNS = (
    "changeme",
    "secret",
    "password",
    "spouet" * 6,  # spouetspouet…
    "aaaa",
)


def _shannon_entropy(s: str) -> float:
    """Entropie de Shannon en bits/char. Un mot de passe aléatoire base64 est
    autour de 5.5–6.0. < 3.5 = chaîne très répétitive."""
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


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

    @field_validator("secret_key")
    @classmethod
    def _validate_secret_key(cls, v: str) -> str:
        low = v.lower()
        for pat in _FORBIDDEN_SECRET_PATTERNS:
            if pat in low:
                raise ValueError(
                    f"SPOUET_SECRET_KEY contient un pattern interdit ({pat!r}). "
                    "Génère une clé aléatoire : `openssl rand -base64 48`."
                )
        if _shannon_entropy(v) < 3.5:
            raise ValueError(
                "SPOUET_SECRET_KEY est trop peu aléatoire (entropie faible). "
                "Génère une clé via `openssl rand -base64 48`."
            )
        return v

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
    # Réseau Docker attaché aux tools déclarant `network: internal` (ceux qui
    # appellent l'API backend, ex. spouet-nodes-status). Doit être le réseau
    # docker-compose où le service `backend` est résolvable.
    tool_docker_network: str = "spouet_default"

    # Connectors persistants
    connector_docker_network: str = "spouet_default"
    connector_backend_url: str = "ws://backend:8000"

    # Voix (microservice voice-engine : STT faster-whisper + TTS Piper)
    voice_enabled: bool = True
    voice_engine_url: str = "http://voice-engine:8001"
    voice_language: str = "fr"
    voice_tts_voice: str = "fr_FR-siwis-medium"
    voice_timeout_s: int = 60
    # Taille max d'un upload audio à transcrire (octets). 25 Mo ~= plusieurs min.
    voice_max_audio_bytes: int = 25 * 1024 * 1024

    # Spotify (OAuth Authorization Code — contrôle de lecture, Premium requis).
    # Créer une app sur https://developer.spotify.com/dashboard et y déclarer le
    # redirect_uri (ex https://spouet.local/api/spotify/callback).
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = ""

    # Nodes
    node_offline_after_s: int = 30
    node_heartbeat_interval_s: int = 10

    # Timeseries : rétention de la table 1-min agrégée (jours). La table raw
    # est toujours purgée à 24h. Plafond hard à 30j même si configuré plus.
    metrics_retention_days: int = 7

    # Chemins serveur (utilisés par les wizards de connectors)
    connectors_registry_dir: str = "/opt/spouet/connectors/registry"

    # API
    api_token_bytes: int = 32
    rate_limit_per_minute: int = 60
    upload_max_bytes: int = 50 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
