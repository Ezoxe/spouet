"""Client HTTP vers l'API de contrôle du node-agent (port `agent_port`).

À ne pas confondre avec `client.py` qui parle à llama-server lui-même.
Ce module orchestre le cycle de vie : démarrage de llama-server, attente
de readiness, gestion des erreurs typées.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from spouet.core.logging import get_logger
from spouet.db.models import Node

logger = get_logger(__name__)

DEFAULT_LOAD_TIMEOUT_S = 180.0
POLL_INTERVAL_S = 1.5
POST_READY_GRACE_S = 1.0


class AgentClientError(RuntimeError):
    """Erreur générique du client agent."""


class AgentUnreachableError(AgentClientError):
    """L'agent ne répond pas (connect refused / timeout)."""


class ModelNotAvailableError(AgentClientError):
    """Le modèle demandé n'est pas présent sur le disque du node."""


class ModelLoadTimeoutError(AgentClientError):
    """Le chargement du modèle a dépassé le timeout."""


def _agent_base(node: Node) -> str | None:
    if node.agent_port is None:
        return None
    return f"http://{node.host}:{node.agent_port}"


async def get_status(node: Node, *, timeout_s: float = 5.0) -> dict[str, Any]:
    """GET /status sur l'agent. Lève AgentUnreachableError si injoignable."""
    base = _agent_base(node)
    if base is None:
        raise AgentUnreachableError(
            f"node '{node.name}' n'a pas d'agent_port (agent legacy ou node direct)"
        )
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.get(f"{base}/status")
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        raise AgentUnreachableError(f"agent {base} unreachable: {e}") from e


async def ensure_model_loaded(
    node: Node,
    model_name: str,
    *,
    timeout_s: float = DEFAULT_LOAD_TIMEOUT_S,
) -> AsyncIterator[dict[str, Any]]:
    """Garantit qu'`model_name` est chargé dans llama-server sur `node`.

    Générateur async qui yield des events `{"event": "loading_model", "data": {...}}`
    consommables tels quels par chat_loop pour relais SSE.

    Lève :
      - AgentUnreachableError si l'agent ne répond pas
      - ModelNotAvailableError si /models/load → 404
      - ModelLoadTimeoutError si le polling dépasse timeout_s
    """
    base = _agent_base(node)
    if base is None:
        # Agent legacy ou node "direct" : on suppose llama-server déjà préchargé.
        return

    # Court-circuit : si déjà chargé, retour immédiat.
    try:
        st = await get_status(node)
        if st.get("llama_running") and st.get("llama_model_loaded") == model_name:
            return
    except AgentUnreachableError:
        raise

    yield {
        "event": "loading_model",
        "data": {
            "node": node.name,
            "model": model_name,
            "phase": "start",
        },
    }

    # POST /models/load (idempotent côté agent : 409 si autre load en cours,
    # 200 si même filename déjà loading).
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{base}/models/load", json={"filename": model_name})
            if r.status_code == 404:
                raise ModelNotAvailableError(
                    f"modèle {model_name!r} absent du node '{node.name}'"
                )
            if r.status_code == 409:
                # Autre load en cours — on bascule en polling, l'utilisateur
                # finira par voir l'état réel.
                logger.info("agent.load_conflict", node=node.name, body=r.text)
            elif r.status_code >= 400:
                raise AgentClientError(
                    f"agent {base} /models/load {r.status_code}: {r.text}"
                )
    except httpx.HTTPError as e:
        raise AgentUnreachableError(f"agent {base} /models/load: {e}") from e

    # Polling de /load/status (fallback sur /status pour les agents anciens).
    started = time.monotonic()
    while True:
        if time.monotonic() - started > timeout_s:
            raise ModelLoadTimeoutError(
                f"chargement de {model_name!r} sur '{node.name}' "
                f"a dépassé {timeout_s:.0f}s"
            )

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{base}/load/status")
                if r.status_code == 200:
                    ls = r.json()
                    state = ls.get("state")
                    if state == "ready" and ls.get("filename") == model_name:
                        break
                    if state == "error":
                        raise ModelLoadTimeoutError(
                            f"agent a remonté une erreur de chargement : "
                            f"{ls.get('error') or 'inconnue'}"
                        )
                else:
                    # Agent ancien sans /load/status → fallback /status
                    s = await client.get(f"{base}/status")
                    if s.status_code == 200:
                        sd = s.json()
                        if (
                            sd.get("llama_running")
                            and sd.get("llama_model_loaded") == model_name
                        ):
                            break
        except httpx.HTTPError as e:
            # On tolère une erreur transitoire pendant le démarrage de llama-server,
            # qui peut faire vaciller l'agent. Le timeout englobant nous protège.
            logger.debug("agent.poll_transient", node=node.name, error=str(e))

        yield {
            "event": "loading_model",
            "data": {
                "node": node.name,
                "model": model_name,
                "phase": "warming",
                "elapsed_s": round(time.monotonic() - started, 1),
            },
        }
        await asyncio.sleep(POLL_INTERVAL_S)

    # Petit délai post-readiness : /health répond avant que /v1/chat/completions
    # ne soit pleinement servable sur de gros modèles.
    await asyncio.sleep(POST_READY_GRACE_S)
    yield {
        "event": "loading_model",
        "data": {
            "node": node.name,
            "model": model_name,
            "phase": "ready",
            "elapsed_s": round(time.monotonic() - started, 1),
        },
    }
