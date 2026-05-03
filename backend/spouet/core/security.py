"""Tokens API : génération, hash, validation."""

from __future__ import annotations

import hashlib
import secrets

from spouet.core.config import settings


def generate_token() -> str:
    """Token API en clair (à montrer une fois à l'utilisateur)."""
    return secrets.token_urlsafe(settings.api_token_bytes)


def hash_token(token: str) -> str:
    """Hash SHA-256 hex (stocké en DB)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    return secrets.compare_digest(hash_token(token), token_hash)
