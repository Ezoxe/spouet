"""Tâches Celery."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from spouet.connectors import manager as connector_manager
from spouet.core.config import settings
from spouet.core.logging import get_logger
from spouet.db.models import Connector, Conversation, JobRun, Node, ScheduledJob, User
from spouet.orchestrator.chat_loop import stream_assistant_reply
from spouet.realtime.hub import publish, user_channel
from spouet.scheduler.syncer import reload_beat_schedule
from spouet.workers.app import celery_app

logger = get_logger(__name__)


@asynccontextmanager
async def _task_db() -> AsyncGenerator[AsyncSession, None]:
    """Session DB isolée par tâche Celery avec NullPool.

    Évite le problème "Future attached to a different loop" causé par le
    prefork de Celery qui hérite d'un engine asyncpg lié à l'event loop
    du processus parent.
    """
    engine = create_async_engine(str(settings.database_url), poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


@celery_app.task(name="spouet.workers.tasks.mark_offline_nodes")
def mark_offline_nodes() -> int:
    return asyncio.run(_mark_offline_nodes_async())


async def _mark_offline_nodes_async() -> int:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=settings.node_offline_after_s)
    async with _task_db() as db:
        result = await db.execute(
            update(Node)
            .where(Node.status == "online", Node.last_seen < threshold)
            .values(status="offline")
        )
        await db.commit()
    count = result.rowcount or 0
    if count:
        logger.info("nodes.marked_offline", count=count)
    return count


@celery_app.task(name="spouet.workers.tasks.sync_scheduler")
def sync_scheduler() -> int:
    """Re-lit la liste des ScheduledJob et reconstruit beat_schedule."""
    n = reload_beat_schedule()
    logger.info("scheduler.synced", jobs=n)
    return n


@celery_app.task(
    name="spouet.workers.tasks.run_scheduled_job",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
)
def run_scheduled_job(self, job_id: str) -> str:  # type: ignore[no-untyped-def]
    return asyncio.run(_run_scheduled_job_async(job_id))


async def _run_scheduled_job_async(job_id: str) -> str:
    async with _task_db() as db:
        job = await db.get(ScheduledJob, UUID(job_id))
        if job is None or not job.enabled:
            return "skipped"

        run = JobRun(job_id=job.id, status="running", started_at=datetime.now(timezone.utc))
        db.add(run)
        await db.commit()
        await db.refresh(run)

        # Conversation éphémère pour ce run
        conv = Conversation(
            user_id=job.user_id,
            title=f"[scheduled] {job.name}",
            model_pref=job.model_pref,
            system_prompt="Tâche planifiée. Réponds de manière concise et structurée.",
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)

        accumulated = ""
        try:
            async for ev in stream_assistant_reply(
                db, conversation=conv, user_text=job.prompt, model_override=job.model_pref
            ):
                if ev["event"] == "token":
                    accumulated += ev["data"].get("text", "")
                elif ev["event"] == "error":
                    raise RuntimeError(ev["data"].get("message", "unknown error"))
            run.status = "ok"
            run.output_text = accumulated
        except Exception as e:  # noqa: BLE001
            run.status = "fail"
            run.error = str(e)
            logger.warning("job.failed", job=job_id, error=str(e))
        finally:
            run.finished_at = datetime.now(timezone.utc)
            job.last_run_at = run.finished_at
            await db.commit()

        # Notif user pour multi-device
        await publish(
            user_channel(job.user_id),
            "job_run",
            {
                "job_id": str(job.id),
                "run_id": str(run.id),
                "status": run.status,
                "name": job.name,
            },
        )
        return run.status


@celery_app.task(name="spouet.workers.tasks.monitor_connectors")
def monitor_connectors() -> int:
    """Refresh statut + redémarre les connectors `enabled` qui ont crashé."""
    return asyncio.run(_monitor_connectors_async())


async def _monitor_connectors_async() -> int:
    from spouet.core.security import generate_token, hash_token

    restarted = 0
    async with _task_db() as db:
        rows = (await db.execute(select(Connector))).scalars().all()
        for row in rows:
            status = await connector_manager.refresh_status(db, row)
            if not row.enabled:
                continue
            if status.state in {"crashed", "stopped"} and (
                row.container_id or status.state == "crashed"
            ):
                # Auto-restart
                raw_token = generate_token()
                row.auth_token_hash = hash_token(raw_token)
                await db.commit()
                await connector_manager.start(db, row, raw_token=raw_token)
                restarted += 1
                logger.info("connector.auto_restart", slug=row.slug)
    if restarted:
        logger.info("connectors.restarted", count=restarted)
    return restarted
