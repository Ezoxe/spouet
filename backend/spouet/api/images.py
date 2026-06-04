"""Routes de génération d'images.

Proxy authentifié vers le microservice image-engine. La page /studio POST
`/generate`, parcourt la galerie via `/`, et affiche chaque image via l'endpoint
de service `/{id}/file` (auth requise → fetch + blob côté front).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from spouet.api.deps import CurrentUser, DbSession
from spouet.core.config import settings
from spouet.core.logging import get_logger
from spouet.db.models import GeneratedImage
from spouet.images import client as image_client
from spouet.images import storage
from spouet.images.client import GenerateParams
from spouet.nodes.router import NoSuitableNodeError, pick_image_node

router = APIRouter()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class GenerateIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str | None = Field(default=None, max_length=2000)
    width: int | None = Field(default=None, ge=64, le=2048)
    height: int | None = Field(default=None, ge=64, le=2048)
    steps: int | None = Field(default=None, ge=1, le=150)
    guidance_scale: float | None = Field(default=None, ge=0.0, le=30.0)
    seed: int | None = None


class ImageOut(BaseModel):
    id: UUID
    prompt: str
    negative_prompt: str | None
    width: int
    height: int
    seed: int | None
    conversation_id: UUID | None
    params: dict
    created_at: datetime
    url: str

    @classmethod
    def of(cls, img: GeneratedImage) -> "ImageOut":
        return cls(
            id=img.id,
            prompt=img.prompt,
            negative_prompt=img.negative_prompt,
            width=img.width,
            height=img.height,
            seed=img.seed,
            conversation_id=img.conversation_id,
            params=img.params_json or {},
            created_at=img.created_at,
            url=f"/api/images/{img.id}/file",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health")
async def images_health(user: CurrentUser, db: DbSession) -> dict:
    """État de la génération d'images : disponibilité d'un node capable."""
    if not settings.images_enabled:
        return {"enabled": False, "ok": False}
    try:
        choice = await pick_image_node(db)
    except NoSuitableNodeError as e:
        return {"enabled": True, "ok": False, "error": str(e)}
    try:
        info = await image_client.health(choice.base_url)
        return {"enabled": True, "ok": True, "node": choice.name, **info}
    except image_client.ImageEngineError as e:
        return {"enabled": True, "ok": False, "node": choice.name, "error": str(e)}


@router.post("/generate", response_model=ImageOut, status_code=status.HTTP_201_CREATED)
async def generate(payload: GenerateIn, user: CurrentUser, db: DbSession) -> ImageOut:
    if not settings.images_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Génération d'images désactivée")
    try:
        choice = await pick_image_node(db)
    except NoSuitableNodeError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    params = GenerateParams(
        prompt=payload.prompt,
        negative_prompt=payload.negative_prompt,
        width=payload.width,
        height=payload.height,
        steps=payload.steps,
        guidance_scale=payload.guidance_scale,
        seed=payload.seed,
    )
    try:
        png = await image_client.generate(choice.base_url, params)
    except image_client.ImageEngineError as e:
        logger.warning("images.generate_failed", error=str(e), node=choice.name)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e

    img = await storage.store(
        db,
        user_id=user.id,
        png=png,
        prompt=payload.prompt,
        negative_prompt=payload.negative_prompt,
        params={
            "node": choice.name,
            "model": choice.image_model,
            **{
                k: v
                for k, v in {
                    "steps": payload.steps,
                    "guidance_scale": payload.guidance_scale,
                }.items()
                if v is not None
            },
        },
        seed=payload.seed,
    )
    return ImageOut.of(img)


@router.get("", response_model=list[ImageOut])
async def list_images(
    user: CurrentUser,
    db: DbSession,
    limit: int = 60,
    offset: int = 0,
) -> list[ImageOut]:
    limit = max(1, min(limit, 200))
    rows = (
        await db.execute(
            select(GeneratedImage)
            .where(GeneratedImage.user_id == user.id)
            .order_by(GeneratedImage.created_at.desc())
            .limit(limit)
            .offset(max(0, offset))
        )
    ).scalars().all()
    return [ImageOut.of(r) for r in rows]


@router.get("/count")
async def count_images(user: CurrentUser, db: DbSession) -> dict:
    total = await db.scalar(
        select(func.count()).select_from(GeneratedImage).where(GeneratedImage.user_id == user.id)
    )
    return {"count": int(total or 0)}


async def _get_owned(db: DbSession, user: CurrentUser, image_id: UUID) -> GeneratedImage:
    img = await db.get(GeneratedImage, image_id)
    if img is None or img.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image introuvable")
    return img


@router.get("/{image_id}/file")
async def get_file(image_id: UUID, user: CurrentUser, db: DbSession) -> Response:
    img = await _get_owned(db, user, image_id)
    data = await storage.read_bytes(img)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fichier manquant")
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_image(image_id: UUID, user: CurrentUser, db: DbSession) -> Response:
    img = await _get_owned(db, user, image_id)
    await storage.delete(db, img)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
