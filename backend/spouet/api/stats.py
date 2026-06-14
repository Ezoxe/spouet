"""Endpoints pour les statistiques d'utilisation (global + par modèle + tendance)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import distinct, func, select

from spouet.api.deps import CurrentUser, DbSession
from spouet.db.models import Conversation, Message

router = APIRouter()


class ModelStat(BaseModel):
    model: str
    messages: int
    tokens_in: int
    tokens_out: int
    latency_ms: int
    avg_tps: float | None
    avg_ttft_ms: float | None
    last_used: str | None


class DayStat(BaseModel):
    day: str  # YYYY-MM-DD (UTC)
    messages: int
    tokens_out: int


class StatsOut(BaseModel):
    # Globaux (compat ascendante)
    tokens_in_total: int
    tokens_out_total: int
    latency_ms_total: int
    messages_count: int
    tokens_per_second: float | None
    # Nouveaux globaux
    conversations_count: int
    avg_latency_ms: float | None
    avg_ttft_ms: float | None
    avg_tokens_out: float | None
    models_used: int
    # Détails
    by_model: list[ModelStat]
    by_day: list[DayStat]


def _tps(tokens_out: int, latency_ms: int) -> float | None:
    if latency_ms > 0 and tokens_out > 0:
        return (tokens_out / latency_ms) * 1000.0
    return None


@router.get("", response_model=StatsOut)
async def get_stats(_: CurrentUser, db: DbSession) -> StatsOut:
    # --- Globaux (messages assistant) ---
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Message.tokens_in), 0),
                func.coalesce(func.sum(Message.tokens_out), 0),
                func.coalesce(func.sum(Message.latency_ms), 0),
                func.count(Message.id),
                func.avg(Message.ttft_ms),
            ).where(Message.role == "assistant")
        )
    ).first()
    tokens_in = int(row[0]) if row else 0
    tokens_out = int(row[1]) if row else 0
    latency_ms = int(row[2]) if row else 0
    count = int(row[3]) if row else 0
    avg_ttft = float(row[4]) if row and row[4] is not None else None

    conversations_count = int(
        (await db.execute(select(func.count(Conversation.id)))).scalar() or 0
    )

    # --- Par modèle ---
    model_rows = (
        await db.execute(
            select(
                Message.model_used,
                func.count(Message.id),
                func.coalesce(func.sum(Message.tokens_in), 0),
                func.coalesce(func.sum(Message.tokens_out), 0),
                func.coalesce(func.sum(Message.latency_ms), 0),
                func.avg(Message.ttft_ms),
                func.max(Message.created_at),
            )
            .where(Message.role == "assistant", Message.model_used.is_not(None))
            .group_by(Message.model_used)
        )
    ).all()
    by_model = [
        ModelStat(
            model=m[0],
            messages=int(m[1]),
            tokens_in=int(m[2]),
            tokens_out=int(m[3]),
            latency_ms=int(m[4]),
            avg_tps=_tps(int(m[3]), int(m[4])),
            avg_ttft_ms=float(m[5]) if m[5] is not None else None,
            last_used=m[6].astimezone(UTC).isoformat().replace("+00:00", "Z") if m[6] else None,
        )
        for m in model_rows
    ]
    by_model.sort(key=lambda s: s.tokens_out, reverse=True)

    # --- Tendance 30 jours (messages assistant / jour, UTC) ---
    cutoff = datetime.now(UTC) - timedelta(days=30)
    day_col = func.date_trunc("day", Message.created_at)
    day_rows = (
        await db.execute(
            select(
                day_col,
                func.count(Message.id),
                func.coalesce(func.sum(Message.tokens_out), 0),
            )
            .where(Message.role == "assistant", Message.created_at >= cutoff)
            .group_by(day_col)
            .order_by(day_col)
        )
    ).all()
    by_day = [
        DayStat(
            day=d[0].date().isoformat() if hasattr(d[0], "date") else str(d[0])[:10],
            messages=int(d[1]),
            tokens_out=int(d[2]),
        )
        for d in day_rows
    ]

    return StatsOut(
        tokens_in_total=tokens_in,
        tokens_out_total=tokens_out,
        latency_ms_total=latency_ms,
        messages_count=count,
        tokens_per_second=_tps(tokens_out, latency_ms),
        conversations_count=conversations_count,
        avg_latency_ms=(latency_ms / count) if count > 0 else None,
        avg_ttft_ms=avg_ttft,
        avg_tokens_out=(tokens_out / count) if count > 0 else None,
        models_used=len(by_model),
        by_model=by_model,
        by_day=by_day,
    )
