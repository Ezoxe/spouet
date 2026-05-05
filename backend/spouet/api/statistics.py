from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select, func

from spouet.api.deps import CurrentUser, DbSession
from spouet.db.models import Message

router = APIRouter()

class TokenStatsOut(BaseModel):
    total_tokens_in: int
    total_tokens_out: int
    total_messages: int
    avg_tokens_per_second: float | None

@router.get("/tokens", response_model=TokenStatsOut)
async def get_token_statistics(_: CurrentUser, db: DbSession) -> TokenStatsOut:
    stmt = select(
        func.sum(Message.tokens_in).label("total_in"),
        func.sum(Message.tokens_out).label("total_out"),
        func.count(Message.id).label("total_msg"),
        func.sum(Message.latency_ms).label("total_latency")
    ).where(Message.role == "assistant")

    result = (await db.execute(stmt)).first()

    total_in = result.total_in or 0
    total_out = result.total_out or 0
    total_msg = result.total_msg or 0
    total_lat = result.total_latency or 0

    avg_tps = None
    if total_lat > 0:
        # tokens per second = (tokens_in + tokens_out) / (latency_ms / 1000)
        avg_tps = (total_in + total_out) / (total_lat / 1000.0)

    return TokenStatsOut(
        total_tokens_in=total_in,
        total_tokens_out=total_out,
        total_messages=total_msg,
        avg_tokens_per_second=avg_tps,
    )
