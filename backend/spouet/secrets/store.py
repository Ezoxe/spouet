"""CRUD du coffre + résolution de références ``scope/key`` → valeur claire."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.crypto import decrypt, encrypt
from spouet.core.logging import get_logger
from spouet.db.models import Secret

logger = get_logger(__name__)


@dataclass(frozen=True)
class SecretRef:
    """Référence ``scope/key`` extraite d'un manifest."""

    scope: str
    key: str

    @classmethod
    def parse(cls, raw: str) -> SecretRef:
        if "/" not in raw:
            raise ValueError(f"référence invalide '{raw}', attendu 'scope/key'")
        scope, key = raw.split("/", 1)
        scope = scope.strip()
        key = key.strip()
        if not scope or not key:
            raise ValueError(f"référence invalide '{raw}'")
        return cls(scope=scope, key=key)

    def as_str(self) -> str:
        return f"{self.scope}/{self.key}"


class SecretMissingError(KeyError):
    """Raised lorsqu'un secret référencé n'existe pas dans le coffre."""


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def upsert(
    db: AsyncSession,
    *,
    scope: str,
    key: str,
    value: str,
    description: str = "",
) -> Secret:
    row = await db.scalar(select(Secret).where(Secret.scope == scope, Secret.key == key))
    if row is None:
        row = Secret(
            scope=scope,
            key=key,
            value_encrypted=encrypt(value),
            description=description,
        )
        db.add(row)
    else:
        row.value_encrypted = encrypt(value)
        if description:
            row.description = description
    await db.commit()
    await db.refresh(row)
    logger.info("secret.upsert", scope=scope, key=key)
    return row


async def delete(db: AsyncSession, *, scope: str, key: str) -> bool:
    row = await db.scalar(select(Secret).where(Secret.scope == scope, Secret.key == key))
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def list_for_scope(db: AsyncSession, scope: str | None = None) -> list[Secret]:
    stmt = select(Secret).order_by(Secret.scope, Secret.key)
    if scope is not None:
        stmt = stmt.where(Secret.scope == scope)
    return list((await db.execute(stmt)).scalars().all())


async def get_value(db: AsyncSession, *, scope: str, key: str) -> str:
    row = await db.scalar(select(Secret).where(Secret.scope == scope, Secret.key == key))
    if row is None:
        raise SecretMissingError(f"{scope}/{key}")
    return decrypt(row.value_encrypted)


async def resolve_env(
    db: AsyncSession,
    mapping: dict[str, str],
    *,
    fallback_scope: str | None = None,
) -> dict[str, str]:
    """Résout un dict ``{ENV_NAME: 'scope/key'}`` en ``{ENV_NAME: 'valeur'}``.

    Si ``fallback_scope`` est fourni, les références sans ``/`` sont préfixées
    automatiquement (ex: ``token`` → ``connector:discord/token``).
    """
    out: dict[str, str] = {}
    missing: list[str] = []
    for env_name, ref in mapping.items():
        if "/" not in ref and fallback_scope:
            ref = f"{fallback_scope}/{ref}"
        try:
            sref = SecretRef.parse(ref)
        except ValueError:
            missing.append(f"{env_name}={ref!r} (format)")
            continue
        try:
            out[env_name] = await get_value(db, scope=sref.scope, key=sref.key)
        except SecretMissingError:
            missing.append(f"{env_name}={sref.as_str()}")
    if missing:
        raise SecretMissingError("Secrets manquants : " + ", ".join(missing))
    return out


def preview(value: str, *, head: int = 3) -> str:
    """Aperçu pour l'UI : ne révèle que les premiers caractères."""
    if not value:
        return ""
    visible = value[:head]
    return f"{visible}{'•' * max(4, len(value) - head)}"
