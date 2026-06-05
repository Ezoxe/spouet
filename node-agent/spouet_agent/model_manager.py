"""Gestion des modèles GGUF locaux : liste, téléchargement, suppression."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LocalModel:
    name: str
    path: str
    size_bytes: int
    parameter_size: str | None = None
    quant: str | None = None


# Modèles GGUF connus comme supportant les tool_calls (détection par nom de fichier)
_TOOL_CAPABLE_KEYWORDS = (
    "llama-3.1", "llama-3.2", "llama-3.3", "llama-4",
    "llama3.1", "llama3.2", "llama3.3", "llama4",
    "qwen2.5", "qwen3", "mistral", "mixtral",
    "command-r", "hermes", "firefunction",
)


def _detect_quant(filename: str) -> str | None:
    """Détecte le niveau de quantification depuis le nom de fichier GGUF."""
    upper = filename.upper()
    for q in ("Q2_K", "Q3_K_S", "Q3_K_M", "Q3_K_L", "Q4_0", "Q4_K_S", "Q4_K_M",
               "Q5_0", "Q5_K_S", "Q5_K_M", "Q6_K", "Q8_0", "F16", "F32", "BF16",
               "IQ1_S", "IQ2_XS", "IQ2_XXS", "IQ3_S", "IQ4_XS", "IQ4_NL"):
        if q in upper:
            return q
    return None


def _detect_param_size(filename: str) -> str | None:
    """Détecte la taille en paramètres (ex: 8B, 70B) depuis le nom de fichier."""
    import re
    m = re.search(r"[_\-](\d+(?:\.\d+)?)[Bb]", filename)
    return f"{m.group(1)}B" if m else None


def list_local_models(models_dir: Path) -> list[LocalModel]:
    """Liste tous les fichiers GGUF dans models_dir (récursif)."""
    if not models_dir.exists():
        return []
    return [
        LocalModel(
            name=f.name,
            path=str(f),
            size_bytes=f.stat().st_size,
            parameter_size=_detect_param_size(f.name),
            quant=_detect_quant(f.name),
        )
        for f in sorted(models_dir.rglob("*.gguf"))
    ]


def model_supports_tools(name: str) -> bool:
    name_lower = name.lower()
    return any(kw.lower() in name_lower for kw in _TOOL_CAPABLE_KEYWORDS)


async def download_model(
    hf_repo: str,
    filename: str,
    dest_dir: Path,
    hf_token: str | None = None,
    progress_callback: "asyncio.Queue[dict] | None" = None,
) -> Path:
    """Télécharge un fichier GGUF depuis Hugging Face Hub.

    Utilise huggingface_hub.hf_hub_download en sous-process pour ne pas bloquer la boucle.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    if dest_path.exists():
        if progress_callback:
            await progress_callback.put({"status": "already_exists", "path": str(dest_path)})
        return dest_path

    if progress_callback:
        await progress_callback.put({"status": "downloading", "repo": hf_repo, "filename": filename})

    loop = asyncio.get_running_loop()
    result_path = await loop.run_in_executor(
        None,
        _download_sync,
        hf_repo,
        filename,
        dest_dir,
        hf_token,
    )

    if progress_callback:
        await progress_callback.put({"status": "done", "path": str(result_path)})

    return result_path


def _download_sync(hf_repo: str, filename: str, dest_dir: Path, hf_token: str | None) -> Path:
    import os
    from huggingface_hub import hf_hub_download  # type: ignore[import-untyped]

    # Force HF_HOME dans le répertoire d'install pour éviter les erreurs de permission
    # si $HOME n'est pas accessible (utilisateur système sans home classique).
    hf_home = dest_dir.parent / ".cache" / "huggingface"
    hf_home.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(hf_home))

    # `local_dir_use_symlinks` est déprécié depuis huggingface_hub 0.23 et
    # ignoré : le téléchargement direct vers local_dir n'utilise plus
    # de symlinks. On le retire pour éviter le warning de deprecation
    # à chaque appel.
    path = hf_hub_download(
        repo_id=hf_repo,
        filename=filename,
        local_dir=str(dest_dir),
        token=hf_token,
    )
    return Path(path)


def delete_model(model_path: Path) -> None:
    if model_path.exists() and model_path.suffix == ".gguf":
        model_path.unlink()


async def check_gguf(
    hf_repo: str, filename: str, hf_token: str | None = None
) -> dict:
    """Pré-vérifie qu'un fichier GGUF est téléchargeable + chargeable par llama.cpp.

    llama.cpp ne charge que des fichiers `.gguf`. On confirme aussi que le fichier
    existe bien dans le repo HF (nom exact) avant de lancer le téléchargement.
    `compatible=None` => indéterminé (repo introuvable / réseau).
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _check_gguf_sync, hf_repo, filename, hf_token)


def _check_gguf_sync(hf_repo: str, filename: str, hf_token: str | None) -> dict:
    name = (filename or "").strip()
    if not name.lower().endswith(".gguf"):
        return {
            "compatible": False,
            "filename": filename,
            "reason": "Le fichier n'est pas un .gguf — llama.cpp ne charge que des modèles GGUF.",
        }
    try:
        from huggingface_hub import HfApi  # type: ignore[import-untyped]

        info = HfApi().repo_info(repo_id=hf_repo, files_metadata=False, token=hf_token or None)
        files = {s.rfilename for s in (info.siblings or [])}
    except Exception as e:  # noqa: BLE001 — réseau / repo absent => indéterminé
        return {"compatible": None, "filename": filename, "reason": f"Repo introuvable ou indisponible : {e}"}

    if name in files or any(f.rsplit("/", 1)[-1] == name for f in files):
        return {"compatible": True, "filename": filename, "reason": "Fichier GGUF présent dans le repo."}
    gguf = sorted(f for f in files if f.lower().endswith(".gguf"))
    hint = f" Fichiers GGUF disponibles : {', '.join(gguf[:6])}" if gguf else ""
    return {
        "compatible": False,
        "filename": filename,
        "reason": f"Fichier « {filename} » absent du repo.{hint}",
    }
