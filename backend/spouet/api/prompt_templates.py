"""Routes prompt-templates : CRUD scopé par user."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.db.models import PromptTemplate

router = APIRouter()


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1)
    shortcut: str | None = Field(default=None, max_length=32)


class TemplatePatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    content: str | None = None
    shortcut: str | None = Field(default=None, max_length=32)


class TemplateOut(BaseModel):
    id: str
    name: str
    content: str
    shortcut: str | None
    created_at: datetime
    updated_at: datetime


def _to_out(t: PromptTemplate) -> TemplateOut:
    return TemplateOut(
        id=str(t.id),
        name=t.name,
        content=t.content,
        shortcut=t.shortcut,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get("", response_model=list[TemplateOut])
async def list_templates(user: CurrentUser, db: DbSession) -> list[TemplateOut]:
    rows = (
        await db.execute(
            select(PromptTemplate)
            .where(PromptTemplate.user_id == user.id)
            .order_by(PromptTemplate.name.asc())
        )
    ).scalars().all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateCreate, user: CurrentUser, db: DbSession
) -> TemplateOut:
    row = PromptTemplate(
        user_id=user.id,
        name=payload.name,
        content=payload.content,
        shortcut=payload.shortcut or None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.patch("/{template_id}", response_model=TemplateOut)
async def patch_template(
    template_id: UUID, payload: TemplatePatch, user: CurrentUser, db: DbSession
) -> TemplateOut:
    row = await db.get(PromptTemplate, template_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    if payload.name is not None:
        row.name = payload.name
    if payload.content is not None:
        row.content = payload.content
    if payload.shortcut is not None:
        row.shortcut = payload.shortcut or None
    await db.commit()
    await db.refresh(row)
    return _to_out(row)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: UUID, user: CurrentUser, db: DbSession) -> None:
    row = await db.get(PromptTemplate, template_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    await db.delete(row)
    await db.commit()
