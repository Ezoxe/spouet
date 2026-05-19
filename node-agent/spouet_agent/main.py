"""Daemon : heartbeat vers le backend Spouet + serveur de contrôle llama.cpp."""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from typing import Annotated

import httpx
import typer
import uvicorn

from spouet_agent import __version__
from spouet_agent.agent_api import app as control_app
from spouet_agent.agent_api import init as init_control
from spouet_agent.capabilities import NodeCapabilities, probe_capabilities
from spouet_agent.gpu import gpu_info_from_capabilities, probe_gpu
from spouet_agent.llama_config import compute_optimal_config, get_model_size_bytes
from spouet_agent.llama_server import LlamaServer, find_llama_server
from spouet_agent.model_manager import list_local_models, model_supports_tools


def _lan_ip() -> str:
    """Retourne l'IP LAN routable (celle de l'interface par défaut)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return socket.gethostname()

AGENT_API_PORT = 8765
LLAMA_SERVER_PORT = 8080

app = typer.Typer(help="Spouet node agent — llama.cpp lifecycle + heartbeat.")


@app.command()
def detect(
    json_out: Annotated[bool, typer.Option("--json", help="Sortie machine-readable")] = False,
) -> None:
    """Affiche les capabilities détectées (compute_class, gpu_kind, llama_variant…).

    Utilisé par les installeurs (install.sh) pour choisir la bonne variante de
    binaire llama-server à télécharger. Une seule source de vérité — finie la
    double détection bash/python qui divergeait.
    """
    caps = probe_capabilities()
    if json_out:
        typer.echo(json.dumps(caps.to_dict(), indent=2))
        return
    typer.echo(f"compute_class : {caps.compute_class}")
    typer.echo(f"gpu_kind      : {caps.gpu_kind}")
    typer.echo(f"gpu_model     : {caps.gpu_model or '—'}")
    typer.echo(f"vram_total_mb : {caps.vram_total_mb or '—'}")
    typer.echo(f"cpu_model     : {caps.cpu_model or '—'}")
    typer.echo(f"cpu_cores     : {caps.cpu_physical_cores}")
    typer.echo(f"cpu_features  : {', '.join(caps.cpu_features) or '—'}")
    typer.echo(f"llama_variant : {caps.llama_variant}")
    typer.echo(f"force_cpu     : {caps.force_cpu}")
    if caps.warnings:
        typer.echo("warnings :")
        for w in caps.warnings:
            typer.echo(f"  • {w}")
    if caps.detection_notes:
        typer.echo("notes :")
        for n in caps.detection_notes:
            typer.echo(f"  • {n}")


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
            host=host or _lan_ip(),
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

    # Détection hardware (source de vérité unique). Le calcul de caps est
    # fait UNE fois ici puis injecté partout — plus de double détection.
    caps = probe_capabilities()
    gpu = gpu_info_from_capabilities(caps)

    server = LlamaServer(
        bin_path=llama_bin or Path("llama-server"),
        models_dir=models_dir,
        port=llama_port,
        capabilities=caps,
    )

    typer.echo(
        f"[spouet-agent {__version__}] "
        f"compute_class={caps.compute_class} gpu_kind={caps.gpu_kind} "
        f"llama_variant={caps.llama_variant} "
        f"GPU={caps.gpu_model or '—'} VRAM={caps.vram_total_mb or '—'}MB "
        f"CPU={caps.cpu_model or '—'} cores={caps.cpu_physical_cores} "
        f"RAM={gpu.ram_total_mb}MB"
    )
    for w in caps.warnings:
        typer.echo(f"[spouet-agent] WARN: {w}", err=True)

    autoload_filename: str | None = None
    autoload_error: str | None = None

    # Charge le modèle autoload si présent
    if autoload and llama_bin:
        # Bloque path-traversal sur la valeur d'autoload (peut venir de l'env).
        if "/" in autoload or "\\" in autoload or ".." in autoload:
            typer.echo(f"[spouet-agent] WARN: autoload value {autoload!r} contient un séparateur de chemin — ignoré", err=True)
        else:
            model_path = models_dir / autoload
            autoload_filename = autoload
            if model_path.exists():
                config = compute_optimal_config(
                    caps=caps,
                    ram_total_mb=gpu.ram_total_mb,
                    model_size_bytes=get_model_size_bytes(model_path),
                )
                typer.echo(f"[spouet-agent] autoloading {autoload}…")
                try:
                    await server.start(model_path, config)
                except Exception as e:
                    autoload_error = str(e)
                    typer.echo(f"[spouet-agent] autoload failed: {e}", err=True)
            else:
                autoload_error = f"model {autoload!r} not found in {models_dir}"
                typer.echo(f"[spouet-agent] WARN: {autoload_error}", err=True)
    elif not autoload:
        # Charge le premier modèle trouvé si aucun n'est spécifié
        local_models = list_local_models(models_dir)
        if local_models and llama_bin:
            first = Path(local_models[0].path)
            autoload_filename = first.name
            config = compute_optimal_config(
                caps=caps,
                ram_total_mb=gpu.ram_total_mb,
                model_size_bytes=get_model_size_bytes(first),
            )
            typer.echo(f"[spouet-agent] autoloading first model {first.name}…")
            try:
                await server.start(first, config)
            except Exception as e:
                autoload_error = str(e)
                typer.echo(f"[spouet-agent] autoload failed: {e}", err=True)

    # Initialise l'API de contrôle (capabilities injectées pour /capabilities et reload)
    init_control(
        server,
        models_dir,
        gpu,
        capabilities=caps,
        autoload_filename=autoload_filename,
        autoload_error=autoload_error,
    )

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
            capabilities=caps,
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


def _read_net_counters() -> tuple[int, int] | None:
    """Lit la somme bytes_rx, bytes_tx sur toutes les interfaces non-loopback.

    Source /proc/net/dev (Linux). Retourne None ailleurs.
    """
    try:
        with open("/proc/net/dev") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    rx = tx = 0
    for line in lines:
        if ":" not in line:
            continue
        iface, rest = line.split(":", 1)
        iface = iface.strip()
        if iface == "lo" or iface.startswith("docker") or iface.startswith("br-"):
            continue
        fields = rest.split()
        if len(fields) < 9:
            continue
        try:
            rx += int(fields[0])
            tx += int(fields[8])
        except ValueError:
            continue
    return rx, tx


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
    capabilities: NodeCapabilities | None = None,
) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    typer.echo(f"[spouet-agent] heartbeat → {backend}/api/nodes/heartbeat as '{name}'")

    # Capabilities calculées une fois au boot ; on les renvoie à chaque
    # heartbeat (le backend persiste en JSONB pour l'admin).
    caps_payload = capabilities.to_dict() if capabilities is not None else None

    # État pour calculer les deltas réseau et CPU entre 2 heartbeats.
    last_net = _read_net_counters()
    last_net_ts = asyncio.get_event_loop().time()
    try:
        import psutil  # type: ignore[import-untyped]

        psutil.cpu_percent(interval=None)  # initialise le compteur cumulatif
        _psutil = psutil
    except ImportError:
        _psutil = None

    async with httpx.AsyncClient() as client:
        while True:
            try:
                # Refresh hardware stats (RAM/VRAM utilisées — les caps sont stables)
                gpu = probe_gpu()
                gpu_info_ref[0] = gpu

                # CPU%
                cpu_pct: float | None = None
                if _psutil is not None:
                    try:
                        cpu_pct = float(_psutil.cpu_percent(interval=None))
                    except Exception:
                        cpu_pct = None

                # Net throughput depuis le dernier heartbeat
                net_rx_kbps: float | None = None
                net_tx_kbps: float | None = None
                net_now = _read_net_counters()
                ts_now = asyncio.get_event_loop().time()
                if net_now is not None and last_net is not None:
                    dt = max(0.001, ts_now - last_net_ts)
                    drx = max(0, net_now[0] - last_net[0])
                    dtx = max(0, net_now[1] - last_net[1])
                    # bytes/s → kbps : *8/1000
                    net_rx_kbps = (drx * 8) / (dt * 1000)
                    net_tx_kbps = (dtx * 8) / (dt * 1000)
                last_net = net_now
                last_net_ts = ts_now

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
                    "capabilities": caps_payload,
                    "cpu_pct": cpu_pct,
                    "net_rx_kbps": net_rx_kbps,
                    "net_tx_kbps": net_tx_kbps,
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
