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

# Tâches périodiques « système ». SOURCE UNIQUE de vérité : `scheduler/syncer.py`
# reconstruit le beat_schedule depuis la DB (jobs utilisateur) et DOIT repartir de
# ce socle, sinon `reload_beat_schedule()` (appelé toutes les 60s par
# `sync_scheduler`) écraserait ces tâches → rollup/purge/partitions/connectors/mail
# s'arrêteraient silencieusement (c'est ce qui vidait node_metrics_1min → 7d KO).
STATIC_BEAT_SCHEDULE: dict[str, dict] = {
    "mark-offline-nodes": {
        "task": "spouet.workers.tasks.mark_offline_nodes",
        "schedule": schedule(15.0),
    },
    "poll-direct-nodes": {
        "task": "spouet.workers.tasks.poll_direct_nodes",
        "schedule": schedule(15.0),
    },
    "monitor-connectors": {
        "task": "spouet.workers.tasks.monitor_connectors",
        "schedule": schedule(30.0),
    },
    "sync-mail-accounts": {
        "task": "spouet.workers.tasks.sync_mail_accounts",
        "schedule": schedule(180.0),  # toutes les 3 min
    },
    # Timeseries : crée les partitions à venir, rollup 1-min, purge ancien
    "create-metrics-partitions": {
        "task": "spouet.workers.tasks.create_metrics_partitions",
        "schedule": schedule(3600.0),  # toutes les heures
    },
    "rollup-metrics-1min": {
        "task": "spouet.workers.tasks.rollup_metrics_1min",
        "schedule": schedule(60.0),
    },
    "purge-metrics-partitions": {
        "task": "spouet.workers.tasks.purge_metrics_partitions",
        "schedule": schedule(3600.0 * 6),  # 4× par jour
    },
    # Resynchronise le beat depuis la DB (jobs utilisateur) toutes les 60s.
    "scheduler-sync": {
        "task": "spouet.workers.tasks.sync_scheduler",
        "schedule": schedule(60.0),
    },
}

celery_app.conf.beat_schedule = dict(STATIC_BEAT_SCHEDULE)
