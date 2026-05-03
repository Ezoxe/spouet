"""Routes scheduled jobs (cron). Implémenté en M4."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from spouet.api.deps import CurrentUser, DbSession
from spouet.db.models import JobRun, ScheduledJob
from spouet.workers.tasks import run_scheduled_job

router = APIRouter()


class JobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    cron: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1)
    tools_allowed: list[str] = Field(default_factory=list)
    model_pref: str | None = None


class JobOut(BaseModel):
    id: str
    name: str
    cron: str
    prompt: str
    tools_allowed: list[str]
    model_pref: str | None
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None


class JobRunOut(BaseModel):
    id: str
    job_id: str
    status: str
    output_text: str
    error: str | None
    tokens_total: int | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


@router.get("", response_model=list[JobOut])
async def list_jobs(user: CurrentUser, db: DbSession) -> list[JobOut]:
    rows = (
        await db.execute(
            select(ScheduledJob)
            .where(ScheduledJob.user_id == user.id)
            .order_by(ScheduledJob.created_at.desc())
        )
    ).scalars().all()
    return [_to_out(j) for j in rows]


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, user: CurrentUser, db: DbSession) -> JobOut:
    job = ScheduledJob(
        user_id=user.id,
        name=payload.name,
        cron=payload.cron,
        prompt=payload.prompt,
        tools_allowed=payload.tools_allowed,
        model_pref=payload.model_pref,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return _to_out(job)


@router.post("/{job_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_run(job_id: UUID, user: CurrentUser, db: DbSession) -> dict[str, str]:
    """Enqueue le job immédiatement (sans attendre le cron)."""
    job = await db.get(ScheduledJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    async_result = run_scheduled_job.delay(str(job.id))
    return {"task_id": async_result.id}


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(job_id: UUID, user: CurrentUser, db: DbSession) -> None:
    job = await db.get(ScheduledJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await db.delete(job)
    await db.commit()


@router.get("/{job_id}/runs", response_model=list[JobRunOut])
async def list_runs(job_id: UUID, user: CurrentUser, db: DbSession) -> list[JobRunOut]:
    job = await db.get(ScheduledJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    rows = (
        await db.execute(
            select(JobRun).where(JobRun.job_id == job_id).order_by(JobRun.created_at.desc()).limit(50)
        )
    ).scalars().all()
    return [
        JobRunOut(
            id=str(r.id),
            job_id=str(r.job_id),
            status=r.status,
            output_text=r.output_text,
            error=r.error,
            tokens_total=r.tokens_total,
            started_at=r.started_at,
            finished_at=r.finished_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


def _to_out(j: ScheduledJob) -> JobOut:
    return JobOut(
        id=str(j.id),
        name=j.name,
        cron=j.cron,
        prompt=j.prompt,
        tools_allowed=j.tools_allowed,
        model_pref=j.model_pref,
        enabled=j.enabled,
        next_run_at=j.next_run_at,
        last_run_at=j.last_run_at,
    )
