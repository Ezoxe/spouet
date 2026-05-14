"""Point d'entrée FastAPI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from spouet import __version__
from spouet.api import (
    stats,
    auth,
    connectors,
    conversations,
    health,
    jobs,
    memory,
    nodes,
    prompt_templates,
    rag,
    secrets as secrets_api,
    tools,
    workspaces,
)
from spouet.api.realtime import connector_ws, sse, websocket
from spouet.core.config import settings
from spouet.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info("spouet.startup", version=__version__)
    yield
    logger.info("spouet.shutdown")


limiter = Limiter(key_func=get_remote_address, default_limits=[f"{settings.rate_limit_per_minute}/minute"])

app = FastAPI(
    title="Spouet",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# REST routes
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(nodes.router, prefix="/api/nodes", tags=["nodes"])
app.include_router(conversations.router, prefix="/api/conversations", tags=["conversations"])
app.include_router(tools.router, prefix="/api/tools", tags=["tools"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"])
app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
app.include_router(secrets_api.router, prefix="/api/secrets", tags=["secrets"])
app.include_router(connectors.router, prefix="/api/connectors", tags=["connectors"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
app.include_router(workspaces.router, prefix="/api/workspaces", tags=["workspaces"])
app.include_router(
    prompt_templates.router, prefix="/api/prompt-templates", tags=["prompt-templates"]
)

# Realtime
app.include_router(sse.router, prefix="/sse", tags=["realtime"])
app.include_router(websocket.router, prefix="/ws", tags=["realtime"])
app.include_router(connector_ws.router, prefix="/ws/connectors", tags=["realtime"])
