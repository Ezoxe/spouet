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

from spouet_agent import __version__, image_gen
from spouet_agent.agent_api import app as control_app
from spouet_agent.agent_api import init as init_control
from spouet_agent.image_api import app as image_app
from spouet_agent.capabilities import NodeCapabilities, probe_capabilities
from spouet_agent.gguf_meta import read_gguf_metadata
from spouet_agent.gpu import gpu_info_from_capabilities, probe_gpu
from spouet_agent.gpu_telemetry import probe_gpu_telemetry
from spouet_agent.llama_config import LlamaConfig, compute_optimal_config, get_model_size_bytes
from spouet_agent.llama_server import LlamaServer, find_llama_server
from spouet_agent.model_manager import list_local_models, model_supports_tools


def _model_n_layers(model_path: Path) -> int | None:
    """Nombre de couches du GGUF (en-tête), ou None si illisible."""
    meta = read_gguf_metadata(model_path)
    return meta.n_layers if meta is not None else None


def _lan_ip() -> str:
    """Retourne l'IP LAN routable (celle de l'interface par défaut)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return socket.gethostname()


def _port_is_free(port: int) -> bool:
    """True si on peut binder 0.0.0.0:port (aucun autre process ne l'occupe).

    On bind sans SO_REUSEADDR pour refléter exactement ce que fera llama-server /
    uvicorn : si ça passe ici, ça passera pour eux. Un simple bind()+close() sans
    connexion établie ne laisse pas de TIME_WAIT, donc pas d'effet de bord.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _find_free_port(preferred: int, exclude: set[int]) -> int:
    """Retourne `preferred` s'il est libre, sinon le 1er port libre au-dessus.

    `exclude` : ports déjà réservés par l'agent lui-même (évite l'auto-collision
    entre llama-server / nommage / image / API de contrôle). Scanne
    preferred..preferred+99 ; en dernier recours, laisse l'OS attribuer un port.
    """
    for port in range(preferred, min(preferred + 100, 65536)):
        if port in exclude:
            continue
        if _port_is_free(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]

AGENT_API_PORT = 8765
LLAMA_SERVER_PORT = 8080
NAMING_SERVER_PORT = 8081
IMAGE_API_PORT = 8083
# Serveur de nommage : petit contexte, CPU, 1 slot — il ne sert que des prompts
# courts pour générer titre + tags.
NAMING_N_CTX = 2048

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
    typer.echo(f"gpu_count     : {caps.gpu_count}")
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
    image_port: Annotated[int, typer.Option("--image-port", help="Port de l'API de génération d'images")] = IMAGE_API_PORT,
    image_model: Annotated[str | None, typer.Option("--image-model", help="Modèle d'images par défaut (repo HF)")] = None,
    image_preload: Annotated[bool, typer.Option("--image-preload", help="Charger le modèle d'images au démarrage")] = False,
    no_images: Annotated[bool, typer.Option("--no-images", help="Désactive la capacité image même si l'extra est installé")] = False,
    naming_model: Annotated[str | None, typer.Option("--naming-model", help="GGUF (nom de fichier) du serveur de nommage dédié, toujours chargé")] = None,
    naming_port: Annotated[int, typer.Option("--naming-port", help="Port du 2e llama-server de nommage")] = NAMING_SERVER_PORT,
    interval: Annotated[int, typer.Option("--interval", min=5, max=300)] = 10,
    tags: Annotated[list[str] | None, typer.Option("--tag", help="Tags du node (répétable)")] = None,
    install_dir: Annotated[str, typer.Option("--install-dir", help="Répertoire d'installation Spouet")] = "/opt/spouet",
    models_dir: Annotated[str | None, typer.Option("--models-dir", envvar="LLAMA_MODELS_DIR")] = None,
    autoload: Annotated[str | None, typer.Option("--autoload", help="Modèle GGUF à charger au démarrage (nom de fichier)")] = None,
) -> None:
    """Boucle infinie : heartbeat + API de contrôle llama.cpp (+ images si extra)."""
    asyncio.run(
        _run(
            backend=backend.rstrip("/"),
            token=token,
            name=name or socket.gethostname(),
            host=host or _lan_ip(),
            llama_port=llama_port,
            agent_port=agent_port,
            image_port=image_port,
            image_model=image_model,
            image_preload=image_preload,
            no_images=no_images,
            naming_model=naming_model,
            naming_port=naming_port,
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
    image_port: int,
    image_model: str | None,
    image_preload: bool,
    no_images: bool,
    naming_model: str | None,
    naming_port: int,
    interval: int,
    tags: list[str],
    install_dir: Path,
    models_dir: Path,
    autoload: str | None,
) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)

    # Auto-résolution des ports : si un port préféré est déjà occupé par un autre
    # programme sur le node, on bascule sur le 1er libre au-dessus. Les ports
    # retenus sont publiés dans le heartbeat → le backend route automatiquement
    # (rien à régler côté admin). On réserve au fur et à mesure pour éviter que
    # deux services de l'agent tombent sur le même port.
    _reserved: set[int] = set()

    def _resolve_port(label: str, preferred: int) -> int:
        chosen = _find_free_port(preferred, _reserved)
        _reserved.add(chosen)
        if chosen != preferred:
            typer.echo(
                f"[spouet-agent] port {label} {preferred} occupé → bascule sur {chosen}.",
                err=True,
            )
        return chosen

    # agent (API de contrôle) et llama-server sont toujours actifs.
    agent_port = _resolve_port("agent", agent_port)
    llama_port = _resolve_port("llama-server", llama_port)

    # Capacité image : seulement si l'extra (torch/diffusers) est installé et non
    # désactivé. C'est le node (machine GPU) qui exécute la génération.
    images_enabled = (not no_images) and image_gen.images_available()
    if images_enabled:
        image_port = _resolve_port("image", image_port)
    if image_model:
        image_gen.set_configured(image_model)
    if images_enabled:
        typer.echo(
            f"[spouet-agent] images activées (device={image_gen.device()}, "
            f"modèle={image_gen.reported_model() or image_gen.default_model()}, port={image_port})"
        )
        if image_preload:
            try:
                await asyncio.to_thread(image_gen.load, image_model)
            except Exception as e:  # noqa: BLE001
                typer.echo(f"[spouet-agent] préchargement image échoué: {e}", err=True)
    elif not no_images:
        typer.echo("[spouet-agent] images désactivées (extra non installé : spouet-agent[images])")

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
                    model_n_layers=_model_n_layers(model_path),
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
                model_n_layers=_model_n_layers(first),
            )
            typer.echo(f"[spouet-agent] autoloading first model {first.name}…")
            try:
                await server.start(first, config)
            except Exception as e:
                autoload_error = str(e)
                typer.echo(f"[spouet-agent] autoload failed: {e}", err=True)

    # 2e llama-server dédié au NOMMAGE (titre/tags) — petit modèle toujours
    # chargé, sur CPU (n_gpu_layers=0) pour ne PAS concurrencer la VRAM du chat.
    # Le backend route l'autoname vers http://{host}:{naming_port}/v1/chat/completions.
    naming_server: LlamaServer | None = None
    naming_loaded: str | None = None
    naming_config: LlamaConfig | None = None
    naming_path: Path | None = None
    if naming_model and llama_bin:
        if "/" in naming_model or "\\" in naming_model or ".." in naming_model:
            typer.echo(f"[spouet-agent] WARN: --naming-model {naming_model!r} invalide — ignoré", err=True)
        else:
            naming_path = models_dir / naming_model
            if naming_path.exists():
                naming_port = _resolve_port("naming", naming_port)
                naming_server = LlamaServer(
                    bin_path=llama_bin, models_dir=models_dir, port=naming_port, capabilities=caps
                )
                naming_config = LlamaConfig(
                    n_ctx=NAMING_N_CTX, n_gpu_layers=0, n_batch=256, n_ubatch=256, n_parallel=1
                )
                typer.echo(
                    f"[spouet-agent] serveur de nommage : {naming_model} "
                    f"(port {naming_port}, CPU, n_ctx={NAMING_N_CTX})…"
                )
                try:
                    await naming_server.start(naming_path, naming_config)
                    naming_loaded = naming_model
                except Exception as e:  # noqa: BLE001
                    typer.echo(f"[spouet-agent] démarrage serveur de nommage échoué: {e}", err=True)
                    naming_server = None
            else:
                typer.echo(
                    f"[spouet-agent] WARN: --naming-model {naming_model!r} absent de "
                    f"{models_dir} — nommage dédié désactivé.",
                    err=True,
                )

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
            images_enabled=images_enabled,
            image_port=image_port,
            naming_server=naming_server,
            naming_port=naming_port,
            naming_model=naming_loaded,
        ),
    ]
    if llama_bin is not None:
        tasks.append(_update_loop(server))
    if images_enabled:
        tasks.append(_serve_image_api(image_port))
    if naming_server is not None and naming_path is not None and naming_config is not None:
        tasks.append(_naming_watchdog(naming_server, naming_path, naming_config))
    await asyncio.gather(*tasks, return_exceptions=True)


async def _naming_watchdog(server: LlamaServer, model_path: Path, config: LlamaConfig) -> None:
    """Garde le serveur de nommage allumé : le relance s'il s'arrête."""
    while True:
        await asyncio.sleep(60)
        if not server.is_running():
            typer.echo("[spouet-agent] serveur de nommage arrêté — redémarrage…", err=True)
            try:
                await server.start(model_path, config)
            except Exception as e:  # noqa: BLE001
                typer.echo(f"[spouet-agent] redémarrage nommage échoué: {e}", err=True)


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


async def _serve_image_api(port: int) -> None:
    config = uvicorn.Config(image_app, host="0.0.0.0", port=port, log_level="warning")
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
    images_enabled: bool = False,
    image_port: int = IMAGE_API_PORT,
    naming_server: LlamaServer | None = None,
    naming_port: int = NAMING_SERVER_PORT,
    naming_model: str | None = None,
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

                # Télémétrie GPU live (par carte) : température, usage, puissance,
                # ventilo, fréquences. Best-effort ([] si indispo).
                tele = probe_gpu_telemetry(capabilities.compute_class if capabilities else "cpu")
                gpu_telemetry_payload = [t.to_dict() for t in tele]
                # Agrégats pour les séries temporelles (1 valeur par node) :
                # température/usage max sur les cartes, puissance totale.
                _temps = [t.temp_c for t in tele if t.temp_c is not None]
                _utils = [t.util_pct for t in tele if t.util_pct is not None]
                _powers = [t.power_w for t in tele if t.power_w is not None]
                gpu_temp_c = max(_temps) if _temps else None
                gpu_util_pct = max(_utils) if _utils else None
                gpu_power_w = round(sum(_powers), 1) if _powers else None
                # VRAM utilisée agrégée : préfère la somme par carte (multi-GPU)
                # à la lecture mono-GPU de gpu.vram_used_mb.
                _vram_used = [t.vram_used_mb for t in tele if t.vram_used_mb is not None]
                if _vram_used:
                    gpu.vram_used_mb = sum(_vram_used)

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

                # Le serveur de nommage est-il prêt à servir ?
                naming_ready = naming_server.is_running() if naming_server is not None else False

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
                    "image_enabled": images_enabled,
                    "image_port": image_port if images_enabled else None,
                    "image_model": image_gen.reported_model() if images_enabled else None,
                    "naming_enabled": naming_ready,
                    "naming_port": naming_port if naming_ready else None,
                    "naming_model": naming_model if naming_ready else None,
                    "cpu_pct": cpu_pct,
                    "net_rx_kbps": net_rx_kbps,
                    "net_tx_kbps": net_tx_kbps,
                    # Télémétrie GPU : snapshot live (par carte) + agrégats série
                    "gpu_telemetry": gpu_telemetry_payload,
                    "gpu_temp_c": gpu_temp_c,
                    "gpu_util_pct": gpu_util_pct,
                    "gpu_power_w": gpu_power_w,
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
