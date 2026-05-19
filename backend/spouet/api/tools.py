"""Routes tools : list / enable / disable. Installation se fait via spouet-admin CLI (M3)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.db.models import Tool
from spouet.tools.approval import submit_decision

router = APIRouter()


class ToolOut(BaseModel):
    id: str
    slug: str
    name: str
    version: str
    description: str
    image: str
    enabled: bool
    network_mode: str
    timeout_s: int
    requires_approval: bool


class ToolPatch(BaseModel):
    enabled: bool | None = None
    requires_approval: bool | None = None


@router.get("", response_model=list[ToolOut])
async def list_tools(_: CurrentUser, db: DbSession) -> list[ToolOut]:
    rows = (await db.execute(select(Tool).order_by(Tool.slug))).scalars().all()
    return [_to_out(t) for t in rows]


@router.patch("/{tool_id}", response_model=ToolOut)
async def patch_tool(
    tool_id: UUID, payload: ToolPatch, _: CurrentUser, db: DbSession
) -> ToolOut:
    tool = await db.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool not found")
    if payload.enabled is not None:
        tool.enabled = payload.enabled
    if payload.requires_approval is not None:
        tool.requires_approval = payload.requires_approval
    await db.commit()
    await db.refresh(tool)
    return _to_out(tool)


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(tool_id: UUID, _: CurrentUser, db: DbSession) -> None:
    """Désinstalle un tool (supprime la row DB). L'image Docker n'est pas
    supprimée du host — c'est une opération séparée et potentiellement
    partagée. ON DELETE CASCADE nettoie l'historique tool_executions lié."""
    tool = await db.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool not found")
    await db.delete(tool)
    await db.commit()


class ApprovalDecision(BaseModel):
    approved: bool
    note: str | None = None


@router.post("/approvals/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def decide_approval(
    request_id: str, payload: ApprovalDecision, _: CurrentUser
) -> None:
    ok = await submit_decision(request_id, approved=payload.approved, note=payload.note)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval request not found or expired")


def _to_out(t: Tool) -> ToolOut:
    return ToolOut(
        id=str(t.id),
        slug=t.slug,
        name=t.name,
        version=t.version,
        description=t.description,
        image=t.image,
        enabled=t.enabled,
        network_mode=t.network_mode,
        timeout_s=t.timeout_s,
        requires_approval=t.requires_approval,
    )
