"""Cycle de vie des conteneurs connectors persistants.

Toute opération Docker est synchrone (docker-py), donc déportée dans un
thread via ``asyncio.to_thread``. Les conteneurs tournent avec
``restart_policy=unless-stopped`` ; le backend leur fournit le WS URL et un
token scopé pour s'authentifier.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import docker
from docker.errors import APIError, ImageNotFound, NotFound
from docker.models.containers import Container
from sqlalchemy.ext.asyncio import AsyncSession

from spouet.core.config import settings
from spouet.core.logging import get_logger
from spouet.db.models import Connector
from spouet.secrets.store import SecretMissingError, resolve_env

logger = get_logger(__name__)


@dataclass
class ConnectorStatus:
    state: str  # 'stopped' | 'running' | 'crashed' | 'starting'
    container_id: str | None
    error: str | None = None


CONTAINER_LABEL = "spouet.connector"


def _client() -> docker.DockerClient:
    return docker.from_env()


def _container_name(connector: Connector) -> str:
    return f"spouet-conn-{connector.slug}-{str(connector.id)[:8]}"


async def start(db: AsyncSession, connector: Connector, *, raw_token: str) -> ConnectorStatus:
    """Lance le conteneur. ``raw_token`` est le token clair généré à l'install
    (le hash est stocké en DB). Il est passé en var d'env au conteneur pour
    qu'il s'authentifie sur la WS."""

    secrets_map = connector.manifest_json.get("secrets") or {}
    try:
        env = (
            await resolve_env(
                db, secrets_map, fallback_scope=f"connector:{connector.slug}"
            )
            if secrets_map
            else {}
        )
    except SecretMissingError as e:
        connector.status = "crashed"
        connector.last_error = str(e)
        await db.commit()
        return ConnectorStatus(state="crashed", container_id=None, error=str(e))

    env.update(
        {
            "SPOUET_BACKEND_URL": settings.connector_backend_url,
            "SPOUET_CONNECTOR_ID": str(connector.id),
            "SPOUET_CONNECTOR_TOKEN": raw_token,
            "SPOUET_CONFIG_JSON": json.dumps(connector.config_json or {}, ensure_ascii=False),
        }
    )

    image = connector.image
    name = _container_name(connector)
    mem_limit = connector.manifest_json.get("mem_limit", "384m")
    cpu_limit = float(connector.manifest_json.get("cpu_limit", 0.5))
    # On utilise *toujours* le réseau partagé docker-compose pour que le
    # connector puisse résoudre 'backend'. La valeur "network" du manifest n'est
    # gardée que pour info (vs runner one-shot).
    network = settings.connector_docker_network

    def _run() -> ConnectorStatus:
        client = _client()
        try:
            client.images.get(image)
        except ImageNotFound:
            # Pull si l'image n'est pas locale (cas des connectors dont l'image
            # vient d'un registre public). Les connectors builds localement
            # passent par CLI install (image déjà présente).
            try:
                logger.info("connector.image_pull", slug=connector.slug, image=image)
                client.images.pull(image)
            except (ImageNotFound, APIError) as e:
                return ConnectorStatus(
                    state="crashed",
                    container_id=None,
                    error=f"image {image!r} not available locally and pull failed: {e}",
                )

        # Stop + remove un éventuel container précédent du même nom
        try:
            old = client.containers.get(name)
            old.stop(timeout=5)
            old.remove(force=True)
        except NotFound:
            pass
        except APIError as e:
            logger.warning("connector.stale_remove_failed", name=name, error=str(e))

        try:
            container = client.containers.run(
                image=image,
                name=name,
                detach=True,
                environment=env,
                network_mode=network,
                mem_limit=mem_limit,
                nano_cpus=int(cpu_limit * 1_000_000_000),
                cap_drop=["ALL"],
                pids_limit=256,
                restart_policy={"Name": "unless-stopped"},
                labels={CONTAINER_LABEL: connector.slug, "spouet.connector_id": str(connector.id)},
                tmpfs={"/tmp": "rw,size=64m,nosuid,noexec,nodev"},
                read_only=True,
            )
        except APIError as e:
            return ConnectorStatus(state="crashed", container_id=None, error=str(e))
        return ConnectorStatus(state="starting", container_id=container.id)

    status = await asyncio.to_thread(_run)
    connector.container_id = status.container_id
    connector.status = status.state
    connector.last_error = status.error
    await db.commit()
    logger.info(
        "connector.start", slug=connector.slug, state=status.state, error=status.error
    )
    return status


async def stop(db: AsyncSession, connector: Connector) -> ConnectorStatus:
    name = _container_name(connector)

    def _run() -> ConnectorStatus:
        client = _client()
        try:
            c = client.containers.get(name)
        except NotFound:
            return ConnectorStatus(state="stopped", container_id=None)
        try:
            c.stop(timeout=5)
            c.remove(force=True)
        except APIError as e:
            return ConnectorStatus(state="crashed", container_id=c.id, error=str(e))
        return ConnectorStatus(state="stopped", container_id=None)

    status = await asyncio.to_thread(_run)
    connector.container_id = None
    connector.status = status.state
    connector.last_error = status.error
    await db.commit()
    logger.info("connector.stop", slug=connector.slug, state=status.state)
    return status


def _inspect_status(c: Container) -> str:
    state = c.attrs.get("State", {}) or {}
    if state.get("Running"):
        return "running"
    if state.get("ExitCode", 0) != 0:
        return "crashed"
    return "stopped"


async def refresh_status(db: AsyncSession, connector: Connector) -> ConnectorStatus:
    name = _container_name(connector)

    def _run() -> ConnectorStatus:
        client = _client()
        try:
            c = client.containers.get(name)
        except NotFound:
            return ConnectorStatus(state="stopped", container_id=None)
        c.reload()
        st = _inspect_status(c)
        err = None
        if st == "crashed":
            err = (c.attrs.get("State") or {}).get("Error") or None
        return ConnectorStatus(state=st, container_id=c.id, error=err)

    status = await asyncio.to_thread(_run)
    connector.container_id = status.container_id
    connector.status = status.state
    connector.last_error = status.error
    await db.commit()
    return status


async def logs(connector: Connector, *, tail: int = 200) -> str:
    name = _container_name(connector)

    def _run() -> str:
        client = _client()
        try:
            c = client.containers.get(name)
        except NotFound:
            return ""
        return c.logs(tail=tail).decode("utf-8", errors="replace")

    return await asyncio.to_thread(_run)


__all__ = [
    "ConnectorStatus",
    "start",
    "stop",
    "refresh_status",
    "logs",
]
