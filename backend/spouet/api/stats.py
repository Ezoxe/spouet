"""Endpoints pour les statistiques."""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from spouet.api.deps import CurrentUser, DbSession
from spouet.db.models import Message

router = APIRouter()

class StatsOut(BaseModel):
    tokens_in_total: int
    tokens_out_total: int
    latency_ms_total: int
    messages_count: int
    tokens_per_second: float | None

@router.get("", response_model=StatsOut)
async def get_stats(_: CurrentUser, db: DbSession) -> StatsOut:
    result = await db.execute(
        select(
            func.sum(Message.tokens_in).label("total_in"),
            func.sum(Message.tokens_out).label("total_out"),
            func.sum(Message.latency_ms).label("total_latency"),
            func.count(Message.id).label("count")
        ).where(Message.role == "assistant")
    )
    row = result.first()

    tokens_in = row.total_in or 0 if row else 0
    tokens_out = row.total_out or 0 if row else 0
    latency_ms = row.total_latency or 0 if row else 0
    count = row.count or 0 if row else 0

    tps = None
    if latency_ms > 0 and tokens_out > 0:
        tps = (tokens_out / latency_ms) * 1000.0

    return StatsOut(
        tokens_in_total=tokens_in,
        tokens_out_total=tokens_out,
        latency_ms_total=latency_ms,
        messages_count=count,
        tokens_per_second=tps
    )
