"""Gestion du cycle de vie du process llama-server."""

from __future__ import annotations

import asyncio
import os
import platform
import re
import shutil
import subprocess as _subprocess
import tarfile as _tarfile
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import httpx
import typer

from spouet_agent.capabilities import NodeCapabilities
from spouet_agent.llama_config import LlamaConfig

GITHUB_LLAMA_LATEST = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"

LLAMA_SERVER_DEFAULT_PORT = 8080
# Plancher : suffit pour les petits modèles (< 8 GB) sur SSD.
STARTUP_TIMEOUT_MIN_S = 180
# Plafond absolu : ~17 minutes même pour les 70B sur HDD lent.
STARTUP_TIMEOUT_MAX_S = 1000
HEALTH_CHECK_INTERVAL_S = 1
# Nombre de lignes de log llama-server conservées pour le diagnostic d'erreur.
LOG_RING_SIZE = 200


@dataclass
class LlamaStats:
    running: bool
    model_loaded: str | None
    n_ctx: int | None
    n_gpu_layers: int | None
    tokens_per_second: float | None
    slots_active: int | None
    prompt_tokens_processed: int | None
    tokens_generated: int | None


class LlamaServerError(RuntimeError):
    pass


def _compute_startup_timeout(model_path: Path) -> int:
    """Timeout adaptatif : ~25s par GB de modèle (HDD lent), borné.

    Permet à un 70B Q4 (40 GB) de prendre jusqu'à 17 min sur HDD, tout en
    restant rapide (180 s) pour un 7B Q4 (4 GB).
    """
    try:
        size_gb = model_path.stat().st_size / (1024 ** 3)
    except OSError:
        return STARTUP_TIMEOUT_MIN_S
    estimated = int(STARTUP_TIMEOUT_MIN_S + size_gb * 25)
    return max(STARTUP_TIMEOUT_MIN_S, min(STARTUP_TIMEOUT_MAX_S, estimated))


class LlamaServer:
    def __init__(
        self,
        bin_path: Path,
        models_dir: Path,
        port: int = LLAMA_SERVER_DEFAULT_PORT,
        capabilities: NodeCapabilities | None = None,
    ) -> None:
        self.bin_path = bin_path
        self.models_dir = models_dir
        self.port = port
        self._capabilities = capabilities
        self._process: asyncio.subprocess.Process | None = None
        self._current_model: Path | None = None
        self._current_config: LlamaConfig | None = None
        self._cumulative_prompt_tokens: int = 0
        self._cumulative_gen_tokens: int = 0
        # Ring buffer des dernières lignes émises par llama-server, utile pour
        # remonter une erreur de démarrage (manque de RAM, lib manquante…).
        self._log_ring: deque[str] = deque(maxlen=LOG_RING_SIZE)
        self._drain_task: asyncio.Task | None = None
        self._last_startup_error: str | None = None

    def _process_env(self) -> dict[str, str]:
        env = os.environ.copy()
        bin_dir = str(self.bin_path.parent)
        # bin_dir en tête pour les .so bundlés + plugins backends.
        extra_paths = [bin_dir, "/usr/local/cuda/lib64", "/usr/lib/x86_64-linux-gnu"]
        prev = env.get("LD_LIBRARY_PATH", "")
        all_paths = ":".join(p for p in extra_paths if p not in prev)
        env["LD_LIBRARY_PATH"] = f"{all_paths}:{prev}" if prev else all_paths
        # Indique explicitement à llama.cpp où chercher les plugins backends.
        env["GGML_BACKEND_DL_PATH"] = bin_dir
        return env

    async def start(self, model_path: Path, config: LlamaConfig) -> None:
        await self.stop()
        cmd = self._build_cmd(model_path, config)
        typer.echo(f"[llama-server] starting: {' '.join(cmd)}")
        self._log_ring.clear()
        self._last_startup_error = None
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            env=self._process_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._current_model = model_path
        self._current_config = config
        # Garde une référence forte sur la tâche : sans ça asyncio peut la GC.
        self._drain_task = asyncio.create_task(self._drain_output())
        timeout = _compute_startup_timeout(model_path)
        try:
            await self._wait_ready(timeout)
        except LlamaServerError:
            # Capture les dernières lignes avant que le process ne soit nettoyé
            # par un éventuel restart, pour faire remonter une cause utile.
            self._last_startup_error = self._format_recent_logs()
            raise
        typer.echo(f"[llama-server] ready on port {self.port}, model={model_path.name}")

    async def stop(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        self._process = None
        if self._drain_task is not None:
            try:
                await asyncio.wait_for(self._drain_task, timeout=2)
            except (asyncio.TimeoutError, Exception):
                pass
            self._drain_task = None

    async def restart(self, model_path: Path | None = None, config: LlamaConfig | None = None) -> None:
        m = model_path or self._current_model
        c = config or self._current_config
        if m is None or c is None:
            raise LlamaServerError("No model/config to restart with")
        await self.start(m, c)

    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def get_recent_logs(self, n: int = 50) -> list[str]:
        """Dernières lignes émises par llama-server (utile pour /diag)."""
        if n <= 0 or n >= len(self._log_ring):
            return list(self._log_ring)
        return list(self._log_ring)[-n:]

    def get_last_startup_error(self) -> str | None:
        return self._last_startup_error

    def _format_recent_logs(self, n: int = 30) -> str:
        lines = self.get_recent_logs(n)
        if not lines:
            return "(aucun log llama-server capturé)"
        return "\n".join(lines)

    async def get_stats(self) -> LlamaStats:
        if not self.is_running():
            return LlamaStats(
                running=False,
                model_loaded=None,
                n_ctx=None,
                n_gpu_layers=None,
                tokens_per_second=None,
                slots_active=None,
                prompt_tokens_processed=None,
                tokens_generated=None,
            )

        tps: float | None = None
        slots_active: int | None = None
        prompt_tokens: int | None = None
        gen_tokens: int | None = None

        try:
            async with httpx.AsyncClient(timeout=3) as client:
                # Slots actifs
                try:
                    r = await client.get(f"http://localhost:{self.port}/slots")
                    if r.status_code == 200:
                        slots = r.json()
                        slots_active = sum(1 for s in slots if s.get("state", 0) != 0)
                except Exception:
                    pass

                # Métriques Prometheus (endpoint activé via --metrics).
                # llama-server préfixe toutes ses métriques par `llamacpp:`.
                # Noms exacts : llamacpp:tokens_predicted_total (génération),
                # llamacpp:prompt_tokens_total (prompt), llamacpp:predicted_tokens_seconds (débit).
                try:
                    mr = await client.get(f"http://localhost:{self.port}/metrics")
                    if mr.status_code == 200:
                        for line in mr.text.splitlines():
                            if line.startswith("#") or not line.strip():
                                continue
                            parts = line.split()
                            if len(parts) < 2:
                                continue
                            name, value = parts[0], parts[-1]
                            try:
                                if name == "llamacpp:tokens_predicted_total":
                                    gen_tokens = int(float(value))
                                elif name == "llamacpp:prompt_tokens_total":
                                    prompt_tokens = int(float(value))
                                elif name == "llamacpp:predicted_tokens_seconds":
                                    tps = float(value)
                            except ValueError:
                                continue
                except Exception:
                    pass
        except Exception:
            pass

        return LlamaStats(
            running=True,
            model_loaded=self._current_model.name if self._current_model else None,
            n_ctx=self._current_config.n_ctx if self._current_config else None,
            n_gpu_layers=self._current_config.n_gpu_layers if self._current_config else None,
            tokens_per_second=tps,
            slots_active=slots_active,
            prompt_tokens_processed=prompt_tokens,
            tokens_generated=gen_tokens,
        )

    def _build_cmd(self, model_path: Path, config: LlamaConfig) -> list[str]:
        # Garde-fou : refuse de demander des couches GPU sur un node CPU-only.
        # Sans ce check, un iGPU mal classé pouvait déclencher --n-gpu-layers != 0
        # sur un binaire CPU → crash silencieux ou erreur "no GPU backend".
        if (
            self._capabilities is not None
            and self._capabilities.compute_class == "cpu"
            and config.n_gpu_layers != 0
        ):
            raise LlamaServerError(
                f"Refus de démarrer llama-server : config demande "
                f"n_gpu_layers={config.n_gpu_layers} mais le node est CPU-only "
                f"(gpu_kind={self._capabilities.gpu_kind}). "
                f"Recompute config ou fixe SPOUET_FORCE_CPU=1."
            )

        cmd = [
            str(self.bin_path),
            "--model", str(model_path),
            "--port", str(self.port),
            "--host", "0.0.0.0",
            "--ctx-size", str(config.n_ctx),
            "--n-gpu-layers", str(config.n_gpu_layers),
            "--batch-size", str(config.n_batch),
            "--ubatch-size", str(config.n_ubatch),
            "--parallel", str(config.n_parallel),
            # Expose /metrics (Prometheus) — désactivé par défaut côté llama-server.
            # Indispensable pour que get_stats() remonte tps/tokens au heartbeat.
            "--metrics",
        ]
        # Flash attention : GPU uniquement — certains modèles (Gemma 4 MoE, etc.)
        # crashent avec --flash-attn sur CPU.
        if config.n_gpu_layers != 0:
            cmd += ["--flash-attn", "on"]
        if config.n_threads is not None:
            cmd += ["--threads", str(config.n_threads)]
        return cmd

    async def _wait_ready(self, timeout: int) -> None:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=2) as client:
            while time.monotonic() - start < timeout:
                if not self.is_running():
                    rc = self._process.returncode if self._process else "?"
                    tail = self._format_recent_logs()
                    raise LlamaServerError(
                        f"llama-server exited with code {rc} during startup\n--- recent output ---\n{tail}"
                    )
                try:
                    r = await client.get(f"http://localhost:{self.port}/health")
                    if r.status_code == 200:
                        return
                except Exception:
                    pass
                await asyncio.sleep(HEALTH_CHECK_INTERVAL_S)
        tail = self._format_recent_logs()
        raise LlamaServerError(
            f"llama-server did not become healthy within {timeout}s\n--- recent output ---\n{tail}"
        )

    async def _drain_output(self) -> None:
        if self._process is None or self._process.stdout is None:
            return
        try:
            async for line in self._process.stdout:
                text = line.decode(errors="replace").rstrip()
                self._log_ring.append(text)
                typer.echo(f"[llama-server] {text}")
        except Exception:
            pass


    def get_installed_version(self) -> str | None:
        """Retourne le tag de build installé (ex. 'b9101'), ou None."""
        if not self.bin_path.exists():
            return None
        try:
            r = _subprocess.run(
                [str(self.bin_path), "--version"],
                capture_output=True, text=True, timeout=10,
                env=self._process_env(),
            )
            output = r.stdout + r.stderr
            m = re.search(r'\bb(\d+)\b', output)
            return m.group(0) if m else None
        except Exception:
            return None

    async def check_and_update(self) -> bool:
        """Vérifie GitHub et met à jour llama-server si une version plus récente existe.
        Retourne True si une mise à jour a été appliquée."""
        # Version actuellement installée
        current = self.get_installed_version()
        current_num = int(current[1:]) if current else None

        # Dernière release GitHub
        async with httpx.AsyncClient(timeout=20, headers={"Accept": "application/vnd.github.v3+json"}) as client:
            try:
                r = await client.get(GITHUB_LLAMA_LATEST)
                r.raise_for_status()
                release = r.json()
            except Exception as exc:
                typer.echo(f"[llama-update] vérification impossible : {exc}", err=True)
                return False

        latest_tag: str = release.get("tag_name", "")
        m = re.search(r'\bb(\d+)\b', latest_tag)
        latest_num = int(m.group(1)) if m else None

        if current_num is not None and latest_num is not None and current_num >= latest_num:
            typer.echo(f"[llama-update] à jour ({current}).")
            return False

        typer.echo(f"[llama-update] mise à jour {current} → {latest_tag}")

        # Détecte GPU et architecture
        gpu_type = _detect_gpu_type()
        arch_tag = {"x86_64": "x64", "aarch64": "arm64"}.get(platform.machine())
        if arch_tag is None:
            typer.echo(f"[llama-update] architecture {platform.machine()} non supportée.", err=True)
            return False

        assets: list[dict] = release.get("assets", [])
        asset_name = _pick_asset(assets, gpu_type, arch_tag)
        if not asset_name:
            typer.echo(f"[llama-update] aucun asset pour {gpu_type}/{arch_tag}.", err=True)
            return False

        url = f"https://github.com/ggml-org/llama.cpp/releases/download/{latest_tag}/{asset_name}"
        typer.echo(f"[llama-update] téléchargement : {url}")

        was_running = self.is_running()

        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir) / "llama.tar.gz"
            try:
                async with httpx.AsyncClient(timeout=600, follow_redirects=True) as dl:
                    async with dl.stream("GET", url) as resp:
                        resp.raise_for_status()
                        with archive.open("wb") as fout:
                            async for chunk in resp.aiter_bytes(65536):
                                fout.write(chunk)
            except Exception as exc:
                typer.echo(f"[llama-update] téléchargement échoué : {exc}", err=True)
                return False

            # Extraire le binaire + les bibliothèques partagées bundlées (.so*)
            new_bin = Path(tmpdir) / "llama-server"
            so_files: list[Path] = []
            try:
                with _tarfile.open(archive) as tar:
                    for member in tar.getmembers():
                        if not member.isfile():
                            continue
                        fname = Path(member.name).name
                        fobj = tar.extractfile(member)
                        if fobj is None:
                            continue
                        if fname == "llama-server":
                            new_bin.write_bytes(fobj.read())
                        elif ".so" in fname:
                            so_path = Path(tmpdir) / fname
                            so_path.write_bytes(fobj.read())
                            so_files.append(so_path)
            except Exception as exc:
                typer.echo(f"[llama-update] extraction échouée : {exc}", err=True)
                return False

            if not new_bin.exists():
                typer.echo("[llama-update] llama-server introuvable dans l'archive.", err=True)
                return False

            new_bin.chmod(0o755)
            if was_running:
                await self.stop()

            target = self.bin_path
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(new_bin), str(target))
                for so in so_files:
                    shutil.move(str(so), str(target.parent / so.name))
            except Exception as exc:
                typer.echo(f"[llama-update] remplacement binaire impossible : {exc}", err=True)
                return False

            # Crée les symlinks SONAME manquants : libfoo.so.0.1.2 → libfoo.so.0
            bin_dir = target.parent
            for so in so_files:
                m = re.match(r'^(.+\.so\.\d+)\.\d+', so.name)
                if m:
                    soname_path = bin_dir / m.group(1)
                    if not soname_path.exists():
                        soname_path.symlink_to(so.name)

        typer.echo(f"[llama-update] ✓ llama-server mis à jour vers {latest_tag}.")

        if was_running:
            try:
                await self.restart()
            except Exception as exc:
                typer.echo(f"[llama-update] redémarrage échoué : {exc}", err=True)

        return True


def _detect_gpu_type() -> str:
    if shutil.which("nvidia-smi"):
        try:
            r = _subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and "GPU" in r.stdout and _cuda_libs_available():
                return "cuda"
        except Exception:
            pass
    if shutil.which("rocm-smi"):
        try:
            if _subprocess.run(["rocm-smi"], capture_output=True, timeout=5).returncode == 0:
                return "rocm"
        except Exception:
            pass
    return "cpu"


def _cuda_libs_available() -> bool:
    """Vérifie que libcuda.so est accessible (drivers + runtime fonctionnels)."""
    try:
        r = _subprocess.run(["ldconfig", "-p"], capture_output=True, text=True, timeout=5)
        if "libcuda.so" in r.stdout:
            return True
    except Exception:
        pass
    for path in ["/usr/local/cuda/lib64", "/usr/lib/x86_64-linux-gnu", "/usr/lib64"]:
        try:
            if any(Path(path).glob("libcuda.so*")):
                return True
        except Exception:
            pass
    return False


def _pick_asset(assets: list[dict], gpu_type: str, arch_tag: str) -> str | None:
    def match(pattern: str) -> str | None:
        for a in assets:
            if re.search(pattern, a["name"], re.IGNORECASE):
                return a["name"]
        return None

    if gpu_type == "cuda":
        cuda_ver = "12"
        try:
            r = _subprocess.run(["nvcc", "--version"], capture_output=True, text=True, timeout=5)
            m = re.search(r'release (\d+)', r.stdout)
            if m:
                cuda_ver = m.group(1)
        except Exception:
            pass
        # Aligné avec install.sh : on cherche debian puis ubuntu, plusieurs variantes.
        for distro in ("debian", "ubuntu"):
            res = (
                match(rf"bin-{distro}-cuda-cu{cuda_ver}-{arch_tag}.*\.tar\.gz")
                or match(rf"bin-{distro}-cuda-cu12-{arch_tag}.*\.tar\.gz")
                or match(rf"bin-{distro}-cuda-{arch_tag}.*\.tar\.gz")
            )
            if res:
                return res
        return None
    if gpu_type == "rocm":
        for distro in ("debian", "ubuntu"):
            res = match(rf"bin-{distro}-rocm[^-]+-{arch_tag}.*\.tar\.gz")
            if res:
                return res
        return None
    # cpu
    for distro in ("debian", "ubuntu"):
        res = (
            match(rf"bin-{distro}-{arch_tag}\.tar\.gz")
            or match(rf"bin-{distro}-{arch_tag}-avx2\.tar\.gz")
            or match(rf"bin-{distro}-{arch_tag}-avx\.tar\.gz")
            or match(rf"bin-{distro}-{arch_tag}-cpu\.tar\.gz")
        )
        if res:
            return res
    return None


def find_llama_server(install_dir: Path) -> Path | None:
    """Cherche llama-server dans install_dir/bin/ puis dans PATH."""
    candidates = [
        install_dir / "bin" / "llama-server",
        install_dir / "bin" / "llama-server.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    found = shutil.which("llama-server")
    return Path(found) if found else None
