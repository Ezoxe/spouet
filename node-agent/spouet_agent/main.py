"""Daemon : heartbeat vers le backend Spouet + serveur de contrôle llama.cpp."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import httpx
import typer
import uvicorn

from spouet_agent import __version__
from spouet_agent.agent_api import app as control_app
from spouet_agent.agent_api import init as init_control
from spouet_agent.gpu import probe_gpu
from spouet_agent.llama_config import compute_optimal_config
from spouet_agent.llama_server import LlamaServer, find_llama_server
from spouet_agent.model_manager import list_local_models, model_supports_tools

AGENT_API_PORT = 8765
LLAMA_SERVER_PORT = 8080

app = typer.Typer(help="Spouet node agent — llama.cpp lifecycle + heartbeat.")


@app.command()
def run(
    backend: Annotated[str, typer.Option("--backend", help="URL du backend Spouet")] = "http://localhost:8000",
    token: Annotated[str, typer.Option("--token", envvar="SPOUET_AGENT_TOKEN")] = ...,  # type: ignore[assignment]
    name: Annotated[str | None, typer.Option("--name", help="Nom du node (défaut: hostname)")] = None,
    host: Annotated[str | None, typer.Option("--host", help="IP routable depuis le backend (défaut: hostname)")] = None,
    llama_port: Annotated[int, typer.Option("--llama-port", help="Port de llama-server")] = LLAMA_SERVER_PORT,
    agent_port: Annotated[int, typer.Option("--agent-port", help="Port de l'API de contrôle")] = AGENT_API_PORT,
    interval: Annotated[int, typer.Option("--interval", min=5, max=300)] = 10,
    tags: Annotated[list[str] | None, typer.Option("--tag", help="Tags du node (répétable)")] = None,
    install_dir: Annotated[str, typer.Option("--install-dir", help="Répertoire d'installation Spouet")] = "/opt/spouet",
    models_dir: Annotated[str | None, typer.Option("--models-dir", envvar="LLAMA_MODELS_DIR")] = None,
    autoload: Annotated[str | None, typer.Option("--autoload", help="Modèle GGUF à charger au démarrage (nom de fichier)")] = None,
) -> None:
    """Boucle infinie : heartbeat + API de contrôle llama.cpp."""
    asyncio.run(
        _run(
            backend=backend.rstrip("/"),
            token=token,
            name=name or socket.gethostname(),
            host=host or socket.gethostname(),
            llama_port=llama_port,
            agent_port=agent_port,
            interval=interval,
            tags=list(tags or []),
            install_dir=Path(install_dir),
            models_dir=Path(models_dir) if models_dir else Path(install_dir) / "models",
            autoload=autoload,
        )
    )


async def _run(
    *,
    backend: str,
    token: str,
    name: str,
    host: str,
    llama_port: int,
    agent_port: int,
    interval: int,
    tags: list[str],
    install_dir: Path,
    models_dir: Path,
    autoload: str | None,
) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)

    # Localise llama-server
    llama_bin = find_llama_server(install_dir)
    if llama_bin is None:
        typer.echo("[spouet-agent] WARN: llama-server not found — serving in heartbeat-only mode.", err=True)

    server = LlamaServer(
        bin_path=llama_bin or Path("llama-server"),
        models_dir=models_dir,
        port=llama_port,
    )

    # Détection hardware initiale
    gpu = probe_gpu()
    typer.echo(f"[spouet-agent {__version__}] GPU={gpu.model} VRAM={gpu.vram_total_mb}MB RAM={gpu.ram_total_mb}MB")

    # Charge le modèle autoload si présent
    if autoload and llama_bin:
        model_path = models_dir / autoload
        if model_path.exists():
            config = compute_optimal_config(gpu.model, gpu.vram_total_mb, gpu.ram_total_mb)
            typer.echo(f"[spouet-agent] autoloading {autoload}…")
            try:
                await server.start(model_path, config)
            except Exception as e:
                typer.echo(f"[spouet-agent] autoload failed: {e}", err=True)
        else:
            typer.echo(f"[spouet-agent] WARN: autoload model {autoload!r} not found in {models_dir}", err=True)
    elif not autoload:
        # Charge le premier modèle trouvé si aucun n'est spécifié
        local_models = list_local_models(models_dir)
        if local_models and llama_bin:
            first = Path(local_models[0].path)
            config = compute_optimal_config(gpu.model, gpu.vram_total_mb, gpu.ram_total_mb)
            typer.echo(f"[spouet-agent] autoloading first model {first.name}…")
            try:
                await server.start(first, config)
            except Exception as e:
                typer.echo(f"[spouet-agent] autoload failed: {e}", err=True)

    # Initialise l'API de contrôle
    init_control(server, models_dir, gpu)

    # Lance l'API de contrôle, le heartbeat, et la mise à jour automatique en parallèle
    tasks: list = [
        _serve_control_api(agent_port),
        _heartbeat_loop(
            backend=backend,
            token=token,
            name=name,
            host=host,
            llama_port=llama_port,
            agent_port=agent_port,
            interval=interval,
            tags=tags,
            server=server,
            models_dir=models_dir,
            gpu_info_ref=[gpu],
        ),
    ]
    if llama_bin is not None:
        tasks.append(_update_loop(server))
    await asyncio.gather(*tasks, return_exceptions=True)


async def _update_loop(server: LlamaServer) -> None:
    """Vérifie et applique les mises à jour llama.cpp toutes les 6h (première vérif après 5 min)."""
    await asyncio.sleep(300)
    while True:
        try:
            await server.check_and_update()
        except Exception as exc:
            typer.echo(f"[llama-update] erreur inattendue : {exc}", err=True)
        await asyncio.sleep(6 * 3600)


async def _serve_control_api(port: int) -> None:
    config = uvicorn.Config(control_app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


async def _heartbeat_loop(
    *,
    backend: str,
    token: str,
    name: str,
    host: str,
    llama_port: int,
    agent_port: int,
    interval: int,
    tags: list[str],
    server: LlamaServer,
    models_dir: Path,
    gpu_info_ref: list,
) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    typer.echo(f"[spouet-agent] heartbeat → {backend}/api/nodes/heartbeat as '{name}'")

    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Refresh hardware stats
                gpu = probe_gpu()
                gpu_info_ref[0] = gpu

                # Stats llama.cpp
                stats = await server.get_stats()

                # Liste des modèles locaux
                local_models = list_local_models(models_dir)
                models_payload = [
                    {
                        "name": m.name,
                        "digest": None,
                        "size_bytes": m.size_bytes,
                        "parameter_size": m.parameter_size,
                        "quant": m.quant,
                        "supports_tools": model_supports_tools(m.name),
                    }
                    for m in local_models
                ]

                payload = {
                    "name": name,
                    "host": host,
                    "port": llama_port,
                    "agent_port": agent_port,
                    "agent_version": __version__,
                    "gpu_model": gpu.model,
                    "vram_total_mb": gpu.vram_total_mb,
                    "vram_used_mb": gpu.vram_used_mb,
                    "ram_total_mb": gpu.ram_total_mb,
                    "ram_used_mb": gpu.ram_used_mb,
                    "disk_total_mb": gpu.disk_total_mb,
                    "disk_used_mb": gpu.disk_used_mb,
                    "llama_running": stats.running,
                    "llama_model_loaded": stats.model_loaded,
                    "llama_n_ctx": stats.n_ctx,
                    "llama_n_gpu_layers": stats.n_gpu_layers,
                    "llama_tps": stats.tokens_per_second,
                    "llama_slots_active": stats.slots_active,
                    "llama_prompt_tokens_processed": stats.prompt_tokens_processed,
                    "llama_tokens_generated": stats.tokens_generated,
                    "tags": tags,
                    "models": models_payload,
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
                        f"[heartbeat] ok models={len(local_models)} "
                        f"llama={'running' if stats.running else 'stopped'} "
                        f"tps={stats.tokens_per_second}"
                    )
            except Exception as e:  # noqa: BLE001
                typer.echo(f"[heartbeat] error: {e}", err=True)
            await asyncio.sleep(interval)


if __name__ == "__main__":
    app()
