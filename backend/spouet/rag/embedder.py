"""Embeddings via Ollama. Sélectionne automatiquement un node qui a le modèle."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.config import settings
from spouet.nodes.client import OllamaError, embed
from spouet.nodes.router import NoSuitableNodeError, pick_node


class EmbeddingError(RuntimeError):
    pass


async def embed_texts(db: AsyncSession, texts: list[str]) -> list[list[float]]:
    """Retourne une matrice (N, D) d'embeddings pour `texts`."""
    if not texts:
        return []
    try:
        choice = await pick_node(db, settings.embedding_model)
    except NoSuitableNodeError as e:
        raise EmbeddingError(f"no node has embedding model '{settings.embedding_model}'") from e
    try:
        return await embed(choice.base_url, model=settings.embedding_model, texts=texts)
    except OllamaError as e:
        raise EmbeddingError(str(e)) from e


async def embed_one(db: AsyncSession, text: str) -> list[float]:
    out = await embed_texts(db, [text])
    return out[0] if out else []
