"""Mémoire long-terme « fichiers .md ».

À la différence de l'ancienne mémoire key/value auto-injectée par recall vectoriel,
chaque souvenir est un **fichier Markdown** que l'IA lit *à la demande* (tools
memory_list / memory_read / memory_write / memory_delete). Seul l'INDEX (noms +
descriptions courtes) est injecté dans le system prompt → contexte compact, et
l'IA décide quoi lire. Inspiré du fonctionnement « MEMORY.md + fichiers » des
agents de code.

Stockage : {settings.memory_dir}/{user_id}/<slug>.md (volume backend+worker).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from spouet.core.config import settings
from spouet.core.logging import get_logger

logger = get_logger(__name__)


class MemoryFileError(RuntimeError):
    pass


@dataclass
class MemoryFile:
    name: str  # slug sans extension (clé stable utilisée par les tools)
    title: str  # titre lisible (1er heading) ou nom
    description: str  # 1re ligne de contenu / résumé court pour l'index
    size_bytes: int
    updated_at: str  # ISO UTC


def _user_dir(user_id: UUID) -> Path:
    d = Path(settings.memory_dir) / str(user_id)
    # Best-effort : si le volume n'est pas inscriptible (droits root sur le bind
    # mount, cf. install.sh chown), on ne fait pas planter l'appel — les lectures
    # renvoient vide, les écritures lèvent MemoryFileError (→ 400, pas 500).
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("memory.dir_unwritable", path=str(d), error=str(e))
    return d


def slugify(name: str) -> str:
    """Nom de fichier sûr (kebab-case ascii, sans extension)."""
    s = unicodedata.normalize("NFKD", str(name or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s or "note")[:80]


def _path_for(user_id: UUID, name: str) -> Path:
    """Chemin absolu sûr pour un nom logique. Anti-traversal : on slugifie."""
    slug = slugify(name)
    return _user_dir(user_id) / f"{slug}.md"


def _describe(content: str) -> tuple[str, str]:
    """Extrait (titre, description) d'un contenu Markdown pour l'index.

    Titre = 1er heading `# ...` ou 1re ligne non vide. Description = 1re ligne de
    texte non-heading (tronquée).
    """
    title = ""
    description = ""
    for raw in content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if not title:
                title = line.lstrip("#").strip()
            continue
        if not description:
            description = line
            if not title:
                title = line
            break
    title = title[:80] or "note"
    description = (description or title)[:160]
    return title, description


def list_files(user_id: UUID) -> list[MemoryFile]:
    d = _user_dir(user_id)
    out: list[MemoryFile] = []
    try:
        paths = sorted(d.glob("*.md"))
    except OSError:
        return []
    for p in paths:
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            st = p.stat()
        except OSError:
            continue
        title, description = _describe(content)
        out.append(
            MemoryFile(
                name=p.stem,
                title=title,
                description=description,
                size_bytes=st.st_size,
                updated_at=datetime.fromtimestamp(st.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
            )
        )
    # Plus récemment modifiés d'abord
    out.sort(key=lambda m: m.updated_at, reverse=True)
    return out


def read_file(user_id: UUID, name: str) -> str | None:
    p = _path_for(user_id, name)
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise MemoryFileError(str(e)) from e


def write_file(user_id: UUID, name: str, content: str) -> MemoryFile:
    slug = slugify(name)
    if not (content or "").strip():
        raise MemoryFileError("contenu vide")
    data = content.encode("utf-8")
    if len(data) > settings.memory_max_file_bytes:
        raise MemoryFileError(
            f"fichier trop volumineux (> {settings.memory_max_file_bytes} octets)"
        )
    d = _user_dir(user_id)
    p = d / f"{slug}.md"
    if not p.exists():
        existing = list(d.glob("*.md"))
        if len(existing) >= settings.memory_max_files_per_user:
            raise MemoryFileError(
                f"quota atteint ({settings.memory_max_files_per_user} fichiers mémoire)"
            )
    try:
        p.write_text(content, encoding="utf-8")
        st = p.stat()
    except OSError as e:
        raise MemoryFileError(f"écriture impossible ({e})") from e
    title, description = _describe(content)
    return MemoryFile(
        name=slug,
        title=title,
        description=description,
        size_bytes=st.st_size,
        updated_at=datetime.fromtimestamp(st.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
    )


def delete_file(user_id: UUID, name: str) -> bool:
    p = _path_for(user_id, name)
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except OSError as e:
        raise MemoryFileError(str(e)) from e


def build_index(user_id: UUID, *, limit: int = 60) -> str | None:
    """Texte d'index (noms + descriptions) injecté dans le system prompt.

    Compact volontairement : l'IA voit CE QUI EXISTE et lit le détail à la demande
    via `memory_read`. None si aucune mémoire.
    """
    files = list_files(user_id)
    if not files:
        return None
    lines = [
        "Mémoire long-terme de l'utilisateur — fichiers Markdown disponibles. "
        "Lis-en un avec le tool `memory_read(name)` quand c'est pertinent ; "
        "crée/maj un souvenir avec `memory_write(name, content)`. N'invente pas leur contenu.",
    ]
    for f in files[:limit]:
        lines.append(f"- `{f.name}` — {f.description}")
    return "\n".join(lines)
