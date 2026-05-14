"""Routes auth : info user courant + rotate token."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from fastapi import APIRouter

from spouet.api.deps import CurrentUser, DbSession
from spouet.core.security import generate_token, hash_token

router = APIRouter()


class MeResponse(BaseModel):
    id: str
    email: str
    default_model: str | None = None


class MePatch(BaseModel):
    default_model: str | None = None


class RotateTokenResponse(BaseModel):
    token: str  # affiché une seule fois


class TokenInfoResponse(BaseModel):
    created_at: datetime | None
    expires_at: datetime | None


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser) -> MeResponse:
    return MeResponse(id=str(user.id), email=user.email, default_model=user.default_model)


@router.patch("/me", response_model=MeResponse)
async def patch_me(payload: MePatch, user: CurrentUser, db: DbSession) -> MeResponse:
    if payload.default_model is not None:
        # chaîne vide = reset
        user.default_model = payload.default_model or None
    await db.commit()
    return MeResponse(id=str(user.id), email=user.email, default_model=user.default_model)


@router.get("/token-info", response_model=TokenInfoResponse)
async def token_info(user: CurrentUser) -> TokenInfoResponse:
    return TokenInfoResponse(created_at=user.token_created_at, expires_at=None)


@router.post("/rotate", response_model=RotateTokenResponse)
async def rotate(user: CurrentUser, db: DbSession) -> RotateTokenResponse:
    """Génère un nouveau token, invalide l'ancien."""
    token = generate_token()
    user.api_token_hash = hash_token(token)
    user.token_created_at = datetime.now(timezone.utc)
    await db.commit()
    return RotateTokenResponse(token=token)
