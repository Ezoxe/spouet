"""Runner Docker sécurisé : un conteneur jetable par appel de tool."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import docker
from docker.errors import APIError, ContainerError, ImageNotFound
from docker.models.containers import Container

from spouet.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ToolResult:
    status: str  # "ok" | "error" | "timeout" | "schema_error"
    stdout: str
    stderr: str
    exit_code: int | None
    duration_ms: int
    container_id: str | None
    parsed: dict[str, Any] | None  # JSON parsé si ok


def _client() -> docker.DockerClient:
    return docker.from_env()


async def run_tool(
    *,
    image: str,
    args: dict[str, Any],
    network: str = "none",
    timeout_s: int = 30,
    mem_limit: str = "256m",
    cpu_limit: float = 1.0,
    env: dict[str, str] | None = None,
) -> ToolResult:
    """Spawn un conteneur jetable, alimente stdin avec args JSON, attend stdout JSON.

    ``env`` est un mapping ``{ENV_VAR: valeur claire}`` injecté dans le conteneur
    (typiquement issu du coffre de secrets). Ne pas logger ces valeurs.
    """
    started = time.monotonic()
    payload = json.dumps(args, ensure_ascii=False).encode("utf-8")

    def _run() -> ToolResult:
        client = _client()
        try:
            client.images.get(image)
        except ImageNotFound:
            return ToolResult(
                status="error",
                stdout="",
                stderr=f"image not found locally: {image}",
                exit_code=None,
                duration_ms=int((time.monotonic() - started) * 1000),
                container_id=None,
                parsed=None,
            )

        container: Container | None = None
        try:
            container = client.containers.create(
                image=image,
                network_mode=network,
                read_only=True,
                cap_drop=["ALL"],
                pids_limit=128,
                mem_limit=mem_limit,
                nano_cpus=int(cpu_limit * 1_000_000_000),
                tmpfs={"/tmp": "rw,size=64m,nosuid,noexec,nodev"},
                environment=env or {},
                stdin_open=True,
                detach=True,
            )

            # Démarre + attache stdin/stdout
            sock = container.attach_socket(
                params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1}
            )
            container.start()
            try:
                sock._sock.sendall(payload)  # type: ignore[union-attr]
                sock._sock.shutdown(1)  # close write side  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass

            try:
                exit_status = container.wait(timeout=timeout_s).get("StatusCode")
            except Exception as e:
                # Timeout / network error : kill et retourne timeout
                logger.warning("tool.timeout", image=image, error=str(e))
                try:
                    container.kill()
                except Exception:  # noqa: BLE001
                    pass
                return ToolResult(
                    status="timeout",
                    stdout="",
                    stderr=f"timeout after {timeout_s}s",
                    exit_code=None,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    container_id=container.id,
                    parsed=None,
                )

            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")

            parsed: dict[str, Any] | None = None
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError:
                parsed = None

            return ToolResult(
                status="ok" if exit_status == 0 and parsed is not None else "error",
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_status,
                duration_ms=int((time.monotonic() - started) * 1000),
                container_id=container.id,
                parsed=parsed,
            )

        except (ContainerError, APIError) as e:
            return ToolResult(
                status="error",
                stdout="",
                stderr=str(e),
                exit_code=None,
                duration_ms=int((time.monotonic() - started) * 1000),
                container_id=container.id if container else None,
                parsed=None,
            )
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:  # noqa: BLE001
                    pass

    # docker-py est synchrone : on déporte dans un thread
    return await asyncio.to_thread(_run)
