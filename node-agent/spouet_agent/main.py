"""Daemon : poste un heartbeat au backend Spouet toutes les N secondes."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import asdict
from typing import Annotated

import httpx
import typer

from spouet_agent import __version__
from spouet_agent.gpu import probe_gpu
from spouet_agent.system import probe_disk, probe_ram
from spouet_agent.ollama import list_models

app = typer.Typer(help="Spouet node agent — heartbeat from an Ollama machine.")


@app.command()
def run(
    backend: Annotated[str, typer.Option("--backend", help="URL du backend Spouet (ex: https://spouet.local)")] = "http://localhost:8000",
    token: Annotated[str, typer.Option("--token", envvar="SPOUET_AGENT_TOKEN")] = ...,  # type: ignore[assignment]
    name: Annotated[str | None, typer.Option("--name", help="Nom du node (par défaut hostname)")] = None,
    ollama_url: Annotated[str, typer.Option("--ollama", help="URL Ollama local")] = "http://localhost:11434",
    ollama_host: Annotated[str | None, typer.Option("--ollama-host", help="Host accessible depuis le backend (par défaut hostname)")] = None,
    ollama_port: Annotated[int, typer.Option("--ollama-port")] = 11434,
    interval: Annotated[int, typer.Option("--interval", min=5, max=300)] = 10,
    tags: Annotated[list[str] | None, typer.Option("--tag", help="Tags du node (répétable)")] = None,
) -> None:
    """Boucle infinie : envoie un heartbeat toutes les `interval` secondes."""
    asyncio.run(
        _run(
            backend=backend.rstrip("/"),
            token=token,
            name=name or socket.gethostname(),
            ollama_url=ollama_url.rstrip("/"),
            ollama_host=ollama_host or socket.gethostname(),
            ollama_port=ollama_port,
            interval=interval,
            tags=list(tags or []),
        )
    )


async def _run(
    *,
    backend: str,
    token: str,
    name: str,
    ollama_url: str,
    ollama_host: str,
    ollama_port: int,
    interval: int,
    tags: list[str],
) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    typer.echo(f"[spouet-agent {__version__}] -> {backend}/api/nodes/heartbeat as '{name}'")
    async with httpx.AsyncClient() as client:
        while True:
            try:
                models = await list_models(ollama_url, client)
                gpu = probe_gpu()
                ram = probe_ram()
                disk = probe_disk()
                payload = {
                    "name": name,
                    "host": ollama_host,
                    "port": ollama_port,
                    "agent_version": __version__,
                    "gpu_model": gpu.model,
                    "vram_total_mb": gpu.vram_total_mb,
                    "vram_used_mb": gpu.vram_used_mb,
                    "ram_total_mb": ram.ram_total_mb,
                    "ram_used_mb": ram.ram_used_mb,
                    "disk_total_mb": disk.disk_total_mb,
                    "disk_used_mb": disk.disk_used_mb,
                    "tags": tags,
                    "models": [asdict(m) for m in models],
                }
                r = await client.post(
                    f"{backend}/api/nodes/heartbeat",
                    json=payload,
                    headers=headers,
                    timeout=10,
                )
                if r.status_code >= 400:
                    typer.echo(f"[heartbeat] {r.status_code} {r.text}", err=True)
                else:
                    typer.echo(
                        f"[heartbeat] ok models={len(models)} vram={gpu.vram_used_mb}/{gpu.vram_total_mb}MB"
                    )
            except Exception as e:  # noqa: BLE001
                typer.echo(f"[heartbeat] error: {e}", err=True)
            await asyncio.sleep(interval)


if __name__ == "__main__":
    app()
