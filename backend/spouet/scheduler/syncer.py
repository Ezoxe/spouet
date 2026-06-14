"""Synchronise les ScheduledJob (DB) → Celery Beat schedule (in-memory).

Architecture pragmatique : pas de scheduler custom, on utilise Celery Beat avec un
schedule périodique qui (re)compose son entry-list depuis la DB. Celery Beat gère le
fire à la bonne heure ; nous nous contentons de lui donner la liste à jour.

Pour une charge faible (quelques dizaines de jobs), c'est suffisant. À haute charge,
remplacer par celery-redbeat ou django-celery-beat.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from celery.schedules import crontab
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from spouet.core.config import settings
from spouet.core.logging import get_logger
from spouet.db.models import ScheduledJob
from spouet.workers.app import STATIC_BEAT_SCHEDULE, celery_app

logger = get_logger(__name__)


def parse_cron(expr: str) -> crontab:
    """Parse un cron 5-fields : 'min hour day month dow'.

    Lève toujours ``ValueError`` sur entrée invalide — y compris pour les champs
    individuels mal formés, où Celery lèverait sinon un ``ParseException`` (qui
    n'hérite pas de ValueError). Normaliser ici garantit que les callers
    (validation API, build_beat_entries) attrapent toutes les erreurs avec un
    seul `except ValueError`.
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"cron must have 5 fields, got {len(parts)}: {expr!r}")
    minute, hour, day, month, dow = parts
    try:
        return crontab(
            minute=minute, hour=hour, day_of_month=day, month_of_year=month, day_of_week=dow
        )
    except ValueError:
        raise
    except Exception as e:  # celery ParseException, etc.
        raise ValueError(f"invalid cron field in {expr!r}: {e}") from e


async def collect_jobs() -> list[ScheduledJob]:
    engine = create_async_engine(str(settings.database_url), poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as db:
            rows = (
                await db.execute(select(ScheduledJob).where(ScheduledJob.enabled.is_(True)))
            ).scalars().all()
            return list(rows)
    finally:
        await engine.dispose()


def build_beat_entries(jobs: list[ScheduledJob]) -> dict[str, dict[str, Any]]:
    # On REPART du socle statique (mark-offline, poll-direct-nodes, monitor-connectors,
    # sync-mail, rollup/purge/partitions métriques, scheduler-sync) puis on ajoute les
    # jobs utilisateur. Sans cette base, reload_beat_schedule() (toutes les 60s)
    # supprimerait les tâches système → notamment rollup_metrics_1min, ce qui vidait
    # node_metrics_1min et cassait la plage 7d.
    entries: dict[str, dict[str, Any]] = dict(STATIC_BEAT_SCHEDULE)
    for j in jobs:
        try:
            sched = parse_cron(j.cron)
        except ValueError as e:
            logger.warning("scheduler.invalid_cron", job=str(j.id), cron=j.cron, error=str(e))
            continue
        entries[f"job-{j.id}"] = {
            "task": "spouet.workers.tasks.run_scheduled_job",
            "schedule": sched,
            "args": (str(j.id),),
        }
    return entries


def reload_beat_schedule() -> int:
    jobs = asyncio.run(collect_jobs())
    entries = build_beat_entries(jobs)
    celery_app.conf.beat_schedule = entries
    return len(jobs)
