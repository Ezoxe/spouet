"""Gestion du cycle de vie du process llama-server."""

from __future__ import annotations

import asyncio
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import typer

from spouet_agent.llama_config import LlamaConfig

LLAMA_SERVER_DEFAULT_PORT = 8080
STARTUP_TIMEOUT_S = 180  # modèles lourds à charger
HEALTH_CHECK_INTERVAL_S = 1


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


class LlamaServer:
    def __init__(self, bin_path: Path, models_dir: Path, port: int = LLAMA_SERVER_DEFAULT_PORT) -> None:
        self.bin_path = bin_path
        self.models_dir = models_dir
        self.port = port
        self._process: asyncio.subprocess.Process | None = None
        self._current_model: Path | None = None
        self._current_config: LlamaConfig | None = None
        self._cumulative_prompt_tokens: int = 0
        self._cumulative_gen_tokens: int = 0

    async def start(self, model_path: Path, config: LlamaConfig) -> None:
        await self.stop()
        cmd = self._build_cmd(model_path, config)
        typer.echo(f"[llama-server] starting: {' '.join(cmd)}")
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._current_model = model_path
        self._current_config = config
        asyncio.create_task(self._drain_output())
        await self._wait_ready()
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

    async def restart(self, model_path: Path | None = None, config: LlamaConfig | None = None) -> None:
        m = model_path or self._current_model
        c = config or self._current_config
        if m is None or c is None:
            raise LlamaServerError("No model/config to restart with")
        await self.start(m, c)

    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

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

                # Métriques Prometheus
                try:
                    mr = await client.get(f"http://localhost:{self.port}/metrics")
                    if mr.status_code == 200:
                        for line in mr.text.splitlines():
                            if line.startswith("#"):
                                continue
                            if "llama_tokens_generated_total" in line:
                                gen_tokens = int(float(line.split()[-1]))
                            elif "llama_prompt_tokens_total" in line:
                                prompt_tokens = int(float(line.split()[-1]))
                            elif "llama_generation_throughput" in line and tps is None:
                                tps = float(line.split()[-1])
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
            "--flash-attn",  # flash attention pour la perf
        ]
        if config.n_threads is not None:
            cmd += ["--threads", str(config.n_threads)]
        return cmd

    async def _wait_ready(self) -> None:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=2) as client:
            while time.monotonic() - start < STARTUP_TIMEOUT_S:
                if not self.is_running():
                    raise LlamaServerError("llama-server process exited during startup")
                try:
                    r = await client.get(f"http://localhost:{self.port}/health")
                    if r.status_code == 200:
                        return
                except Exception:
                    pass
                await asyncio.sleep(HEALTH_CHECK_INTERVAL_S)
        raise LlamaServerError(f"llama-server did not start within {STARTUP_TIMEOUT_S}s")

    async def _drain_output(self) -> None:
        if self._process is None or self._process.stdout is None:
            return
        try:
            async for line in self._process.stdout:
                text = line.decode(errors="replace").rstrip()
                typer.echo(f"[llama-server] {text}")
        except Exception:
            pass


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
