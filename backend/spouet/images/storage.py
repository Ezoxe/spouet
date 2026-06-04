"""Stockage sur disque des images générées + métadonnées en base.

Les octets PNG vivent dans ``settings.images_dir`` (volume persistant) ; la table
``generated_images`` ne garde que le chemin relatif + les métadonnées. Un quota
par utilisateur (``image_max_per_user``) élague les plus anciennes pour borner la
croissance du disque.
"""

from __future__ import annotations

import os
import struct
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from spouet.core.config import settings
from spouet.core.logging import get_logger
from spouet.db.models import GeneratedImage

logger = get_logger(__name__)


def _root() -> str:
    os.makedirs(settings.images_dir, exist_ok=True)
    return settings.images_dir


def abspath(image: GeneratedImage) -> str:
    return os.path.join(settings.images_dir, image.file_path)


def _png_dimensions(data: bytes) -> tuple[int, int]:
    """Lit largeur/hauteur depuis l'en-tête IHDR d'un PNG (offsets 16-24)."""
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    return 0, 0


async def store(
    db: AsyncSession,
    *,
    user_id: UUID,
    png: bytes,
    prompt: str,
    negative_prompt: str | None,
    params: dict,
    seed: int | None,
    conversation_id: UUID | None = None,
) -> GeneratedImage:
    """Écrit le PNG sur disque, insère la ligne, applique le quota."""
    width, height = _png_dimensions(png)
    rel = f"{uuid4().hex}.png"
    path = os.path.join(_root(), rel)
    await run_in_threadpool(_write_file, path, png)

    image = GeneratedImage(
        user_id=user_id,
        conversation_id=conversation_id,
        prompt=prompt,
        negative_prompt=negative_prompt or None,
        file_path=rel,
        width=width,
        height=height,
        seed=seed,
        params_json=params,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    await _enforce_quota(db, user_id)
    return image


def _write_file(path: str, data: bytes) -> None:
    with open(path, "wb") as f:
        f.write(data)


async def read_bytes(image: GeneratedImage) -> bytes | None:
    path = abspath(image)
    if not os.path.isfile(path):
        return None
    return await run_in_threadpool(_read_file, path)


def _read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


async def delete(db: AsyncSession, image: GeneratedImage) -> None:
    path = abspath(image)
    await db.delete(image)
    await db.commit()
    try:
        await run_in_threadpool(os.remove, path)
    except OSError:
        pass


async def _enforce_quota(db: AsyncSession, user_id: UUID) -> None:
    """Supprime les images les plus anciennes au-delà de ``image_max_per_user``."""
    cap = settings.image_max_per_user
    if cap <= 0:
        return
    rows = (
        await db.execute(
            select(GeneratedImage)
            .where(GeneratedImage.user_id == user_id)
            .order_by(GeneratedImage.created_at.desc())
            .offset(cap)
        )
    ).scalars().all()
    for old in rows:
        path = abspath(old)
        await db.delete(old)
        try:
            await run_in_threadpool(os.remove, path)
        except OSError:
            pass
    if rows:
        await db.commit()
