"""Dépendances FastAPI : auth, DB, etc."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.security import hash_token
from spouet.db import get_db
from spouet.db.models import User

TOKEN_EXPIRY_HOURS = 24


async def current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Empty token")
    token_hash = hash_token(token)
    user = await db.scalar(
        select(User).where(User.api_token_hash == token_hash, User.is_active.is_(True))
    )
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    if user.token_created_at is not None:
        age = datetime.now(timezone.utc) - user.token_created_at
        if age > timedelta(hours=TOKEN_EXPIRY_HOURS):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
