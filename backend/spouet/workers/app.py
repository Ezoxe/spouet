"""Celery app + beat schedule (M2+ pour les tâches métier)."""

from __future__ import annotations

from celery import Celery
from celery.schedules import schedule

from spouet.core.config import settings

celery_app = Celery(
    "spouet",
    broker=str(settings.redis_url),
    backend=str(settings.redis_url),
    include=["spouet.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=10,
    task_default_max_retries=3,
)

# Tâches périodiques minimales (M1) : marquer les nodes offline
celery_app.conf.beat_schedule = {
    "mark-offline-nodes": {
        "task": "spouet.workers.tasks.mark_offline_nodes",
        "schedule": schedule(15.0),
    },
    "monitor-connectors": {
        "task": "spouet.workers.tasks.monitor_connectors",
        "schedule": schedule(30.0),
    },
}
