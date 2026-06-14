"""Auto-update du node-agent piloté par le backend (via la réponse au heartbeat).

Principe (sûr, sans root) : le backend connaît le commit git cible du monorepo
déployé (stampé par `install.sh`). Quand l'agent rapporte un commit différent, le
heartbeat répond ``update_available=true``. L'agent — qui possède son repo
(`/opt/spouet`, utilisateur `spouet`) — fait alors un ``git pull`` puis **sort
proprement**. systemd (`Restart=always`) / NSSM relancent le service, et
``uv run`` resynchronise les dépendances avant de redémarrer le code à jour.

Aucune élévation de privilège : l'agent ne touche pas à systemd, c'est le
gestionnaire de service qui le relance. Désactivable via
``SPOUET_AGENT_AUTO_UPDATE=0``.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import typer

# Anti-hammering : délai minimal entre deux tentatives de self-update (en cas
# d'échec du pull, on ne réessaie pas à chaque heartbeat).
_RETRY_COOLDOWN_S = 300.0
_last_attempt_at: float = 0.0
_in_progress = False


def auto_update_enabled() -> bool:
    """Auto-update actif sauf si SPOUET_AGENT_AUTO_UPDATE ∈ {0,false,no,off}."""
    val = os.environ.get("SPOUET_AGENT_AUTO_UPDATE", "1").strip().lower()
    return val not in {"0", "false", "no", "off"}


async def read_git_commit(install_dir: Path) -> str | None:
    """SHA court du HEAD du repo `install_dir`, ou None si non-git / git absent."""
    if not (install_dir / ".git").exists():
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            f"safe.directory={install_dir}",
            "-C",
            str(install_dir),
            "rev-parse",
            "--short",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            return out.decode().strip() or None
    except (OSError, asyncio.TimeoutError):
        return None
    return None


async def _git_pull(install_dir: Path) -> bool:
    """`git pull --ff-only` dans install_dir. True si succès."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            f"safe.directory={install_dir}",
            "-C",
            str(install_dir),
            "pull",
            "--ff-only",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        msg = out.decode(errors="replace").strip()
        if proc.returncode == 0:
            typer.echo(f"[self-update] git pull ok: {msg.splitlines()[-1] if msg else 'à jour'}")
            return True
        typer.echo(f"[self-update] git pull a échoué (rc={proc.returncode}): {msg}", err=True)
        return False
    except (OSError, asyncio.TimeoutError) as e:
        typer.echo(f"[self-update] git pull error: {e}", err=True)
        return False


async def maybe_self_update(install_dir: Path, target_commit: str | None) -> bool:
    """Tente une mise à jour si l'auto-update est actif et le cooldown passé.

    Fait un ``git pull --ff-only``. Retourne ``True`` si le code a été mis à jour
    et que l'agent doit redémarrer (l'appelant arrête proprement llama-server puis
    quitte → le gestionnaire de service relance sur le nouveau code). ``False``
    sinon (désactivé, cooldown, non-git, ou pull échoué). Cooldown anti-boucle.
    """
    global _last_attempt_at, _in_progress
    if _in_progress or not auto_update_enabled():
        return False
    now = time.monotonic()
    if now - _last_attempt_at < _RETRY_COOLDOWN_S:
        return False
    _last_attempt_at = now
    _in_progress = True
    try:
        typer.echo(
            f"[self-update] le backend signale une nouvelle version "
            f"(cible={target_commit}). Mise à jour…"
        )
        if not (install_dir / ".git").exists():
            typer.echo(
                f"[self-update] {install_dir} n'est pas un dépôt git — "
                f"mise à jour manuelle requise.",
                err=True,
            )
            _in_progress = False
            return False
        if not await _git_pull(install_dir):
            _in_progress = False  # autorise une nouvelle tentative après cooldown
            return False
        # Succès : on laisse _in_progress=True (le process va se terminer) et on
        # signale à l'appelant de redémarrer proprement.
        return True
    except Exception as e:  # noqa: BLE001
        typer.echo(f"[self-update] erreur inattendue: {e}", err=True)
        _in_progress = False
        return False
