"""Routes REST du coffre de secrets.

Les valeurs en clair ne sont **jamais** retournées : seules les métadonnées et
un aperçu masqué (``preview``) sont exposés. Pour modifier un secret, il faut
poster une nouvelle valeur (PUT).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from spouet.api.deps import CurrentUser, DbSession
from spouet.core.crypto import SecretDecryptionError, decrypt
from spouet.secrets import store

router = APIRouter()


class SecretOut(BaseModel):
    scope: str
    key: str
    description: str
    preview: str
    decryptable: bool


class SecretIn(BaseModel):
    scope: str = Field(min_length=1, max_length=120)
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1)
    description: str = ""


@router.get("", response_model=list[SecretOut])
async def list_secrets(
    _: CurrentUser, db: DbSession, scope: str | None = None
) -> list[SecretOut]:
    rows = await store.list_for_scope(db, scope)
    out: list[SecretOut] = []
    for r in rows:
        try:
            preview_text = store.preview(decrypt(r.value_encrypted))
            decryptable = True
        except SecretDecryptionError:
            preview_text = "⚠️ undecryptable"
            decryptable = False
        out.append(
            SecretOut(
                scope=r.scope,
                key=r.key,
                description=r.description,
                preview=preview_text,
                decryptable=decryptable,
            )
        )
    return out


@router.put("", response_model=SecretOut)
async def upsert_secret(payload: SecretIn, _: CurrentUser, db: DbSession) -> SecretOut:
    row = await store.upsert(
        db,
        scope=payload.scope,
        key=payload.key,
        value=payload.value,
        description=payload.description,
    )
    return SecretOut(
        scope=row.scope,
        key=row.key,
        description=row.description,
        preview=store.preview(payload.value),
        decryptable=True,
    )


@router.delete("/{scope}/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(scope: str, key: str, _: CurrentUser, db: DbSession) -> None:
    ok = await store.delete(db, scope=scope, key=key)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "secret not found")
