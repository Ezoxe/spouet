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
from spouet.db.models import Connector, Conversation, JobRun, Model, Node, ScheduledJob, User
from spouet.nodes.client import DIRECT_AGENT_MARKER, probe as probe_ollama
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


@celery_app.task(name="spouet.workers.tasks.poll_direct_nodes")
def poll_direct_nodes() -> int:
    """Ping les nodes Ollama enregistrés sans agent (`agent_version='direct'`)."""
    return asyncio.run(_poll_direct_nodes_async())


async def _poll_direct_nodes_async() -> int:
    polled = 0
    async with _task_db() as db:
        rows = (
            await db.execute(select(Node).where(Node.agent_version == DIRECT_AGENT_MARKER))
        ).scalars().all()
        for node in rows:
            now = datetime.now(timezone.utc)
            result = await probe_ollama(f"http://{node.host}:{node.port}")
            if not result.reachable:
                node.status = "offline"
                # On ne touche pas last_seen : le sweep mark_offline_nodes l'utilise.
                continue
            node.status = "online"
            node.last_seen = now

            existing = {
                m.name: m
                for m in (
                    await db.execute(select(Model).where(Model.node_id == node.id))
                ).scalars().all()
            }
            seen: set[str] = set()
            for m in result.models:
                seen.add(m.name)
                if m.name in existing:
                    row = existing[m.name]
                    row.digest = m.digest
                    row.size_bytes = m.size_bytes
                    row.quant = m.quant
                    row.parameter_size = m.parameter_size
                    row.supports_tools = m.supports_tools
                    row.last_seen = now
                else:
                    db.add(
                        Model(
                            node_id=node.id,
                            name=m.name,
                            digest=m.digest,
                            size_bytes=m.size_bytes,
                            quant=m.quant,
                            parameter_size=m.parameter_size,
                            supports_tools=m.supports_tools,
                            last_seen=now,
                        )
                    )
            for name, row in existing.items():
                if name not in seen:
                    await db.delete(row)
            polled += 1
        await db.commit()
    if polled:
        logger.info("nodes.polled_direct", count=polled)
    return polled


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


# ---------------------------------------------------------------------------
# Timeseries node_metrics : partition lifecycle + rollup 1-min
# ---------------------------------------------------------------------------


@celery_app.task(name="spouet.workers.tasks.create_metrics_partitions")
def create_metrics_partitions() -> int:
    """Crée les partitions journalières de J et J+1 pour les 2 tables timeseries.

    Idempotent (CREATE TABLE IF NOT EXISTS). Tourne toutes les heures pour
    couvrir le rollover de minuit sans risquer une perte d'écritures.
    """
    return asyncio.run(_create_metrics_partitions_async())


async def _create_metrics_partitions_async() -> int:
    from sqlalchemy import text

    today = datetime.now(timezone.utc).date()
    days = [today, today + timedelta(days=1)]
    created = 0
    async with _task_db() as db:
        for d in days:
            start = d.isoformat()
            end = (d + timedelta(days=1)).isoformat()
            suffix = d.strftime("%Y%m%d")
            for parent in ("node_metrics_raw", "node_metrics_1min"):
                pname = f"{parent}_p{suffix}"
                # CREATE TABLE IF NOT EXISTS pour les partitions n'existe pas en
                # standard ; on passe par pg_class pour tester avant CREATE.
                exists = await db.scalar(
                    text("SELECT to_regclass(:pname)").bindparams(pname=pname)
                )
                if exists:
                    continue
                await db.execute(
                    text(
                        f"CREATE TABLE {pname} PARTITION OF {parent} "
                        f"FOR VALUES FROM ('{start}') TO ('{end}')"
                    )
                )
                created += 1
                logger.info("metrics.partition_created", table=pname)
        await db.commit()
    return created


@celery_app.task(name="spouet.workers.tasks.rollup_metrics_1min")
def rollup_metrics_1min() -> int:
    """Agrège la dernière minute de node_metrics_raw vers node_metrics_1min.

    Fenêtre tumbling : [now - 2min, now - 1min). Latence d'1 min pour s'assurer
    que tous les heartbeats de la minute cible sont arrivés.
    """
    return asyncio.run(_rollup_metrics_1min_async())


async def _rollup_metrics_1min_async() -> int:
    from sqlalchemy import text

    # Tronque now à la minute supérieure puis recule de 2 min pour la borne basse.
    async with _task_db() as db:
        result = await db.execute(
            text(
                """
                INSERT INTO node_metrics_1min (
                    time, node_id,
                    cpu_pct, ram_used_mb, ram_total_mb,
                    vram_used_mb, vram_total_mb, disk_used_mb,
                    net_rx_kbps, net_tx_kbps,
                    llama_running, llama_model_loaded, llama_tps,
                    llama_slots_active, llama_prompt_tokens_total,
                    llama_gen_tokens_total, llama_queue_pending
                )
                SELECT
                    date_trunc('minute', time) AS time,
                    node_id,
                    AVG(cpu_pct)::real,
                    MAX(ram_used_mb)::int,
                    MAX(ram_total_mb)::int,
                    MAX(vram_used_mb)::int,
                    MAX(vram_total_mb)::int,
                    MAX(disk_used_mb)::int,
                    AVG(net_rx_kbps)::real,
                    AVG(net_tx_kbps)::real,
                    bool_or(llama_running),
                    (array_agg(llama_model_loaded ORDER BY time DESC))[1],
                    AVG(llama_tps)::real,
                    MAX(llama_slots_active)::int,
                    MAX(llama_prompt_tokens_total),
                    MAX(llama_gen_tokens_total),
                    MAX(llama_queue_pending)::int
                FROM node_metrics_raw
                WHERE time >= date_trunc('minute', now()) - interval '2 minutes'
                  AND time <  date_trunc('minute', now()) - interval '1 minute'
                GROUP BY date_trunc('minute', time), node_id
                ON CONFLICT (node_id, time) DO NOTHING
                """
            )
        )
        await db.commit()
    return result.rowcount or 0


@celery_app.task(name="spouet.workers.tasks.purge_metrics_partitions")
def purge_metrics_partitions() -> int:
    """Drop les partitions de raw plus vieilles que 24h et 1min plus vieilles
    que SPOUET_METRICS_RETENTION_DAYS jours (default 7)."""
    return asyncio.run(_purge_metrics_partitions_async())


async def _purge_metrics_partitions_async() -> int:
    from sqlalchemy import text

    retention_days = getattr(settings, "metrics_retention_days", 7)
    today = datetime.now(timezone.utc).date()
    raw_keep_from = today - timedelta(days=1)
    agg_keep_from = today - timedelta(days=retention_days)

    dropped = 0
    async with _task_db() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT inhrelid::regclass::text AS pname,
                           parent.relname AS parent_name
                    FROM pg_inherits
                    JOIN pg_class parent ON parent.oid = inhparent
                    WHERE parent.relname IN ('node_metrics_raw', 'node_metrics_1min')
                    """
                )
            )
        ).all()
        for r in rows:
            pname = r.pname
            parent = r.parent_name
            # Format attendu : <parent>_p20260513
            try:
                suffix = pname.rsplit("_p", 1)[1]
                pdate = datetime.strptime(suffix, "%Y%m%d").date()
            except (IndexError, ValueError):
                continue  # _default ou format inattendu — on garde
            cutoff = raw_keep_from if parent == "node_metrics_raw" else agg_keep_from
            if pdate < cutoff:
                await db.execute(text(f"DROP TABLE IF EXISTS {pname}"))
                dropped += 1
                logger.info("metrics.partition_dropped", table=pname)
        await db.commit()
    return dropped


@celery_app.task(name="spouet.workers.tasks.sync_mail_accounts")
def sync_mail_accounts() -> int:
    """Synchronise toutes les boîtes mail activées (fetch + tri IA + brouillons)."""
    return asyncio.run(_sync_mail_accounts_async())


async def _sync_mail_accounts_async() -> int:
    import redis.asyncio as redis  # type: ignore[import-untyped]

    from spouet.db.models import MailAccount
    from spouet.mail.sync import sync_account

    # Verrou global : un seul cycle de synchro à la fois (évite que deux ticks
    # beat se chevauchent si la synchro déborde l'intervalle).
    cli = redis.from_url(str(settings.redis_url), decode_responses=True)
    try:
        got = await cli.set("lock:mail_sync", "1", nx=True, ex=600)
        if not got:
            return 0
        synced = 0
        async with _task_db() as db:
            rows = (
                await db.execute(select(MailAccount).where(MailAccount.enabled.is_(True)))
            ).scalars().all()
            for acc in rows:
                try:
                    await sync_account(db, acc)
                    synced += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning("mail.sync_account_failed", account=str(acc.id), error=str(e))
        if synced:
            logger.info("mail.synced", accounts=synced)
        return synced
    finally:
        try:
            await cli.delete("lock:mail_sync")
        finally:
            await cli.aclose()


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
