"""Lecteur minimal d'en-tête GGUF — uniquement les métadonnées utiles.

But : récupérer le **nombre de couches** (`<arch>.block_count`) d'un modèle sans
le charger, pour calculer un offload GPU partiel quand il ne tient pas en VRAM
(cf. `llama_config.compute_optimal_config`).

On ne lit QUE la zone de métadonnées (jamais les tenseurs). 100% défensif :
toute anomalie → `None` (l'appelant retombe alors sur `n_gpu_layers=-1`).

Format GGUF : magic `GGUF`, version (u32), tensor_count (u64), kv_count (u64),
puis kv_count paires {clé: gguf_string, type: u32, valeur: typée}. Réf :
https://github.com/ggml-org/ggml/blob/master/docs/gguf.md
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

# Types de valeur GGUF → taille en octets (scalaires à largeur fixe).
_SCALAR_SIZES = {
    0: 1,   # UINT8
    1: 1,   # INT8
    2: 2,   # UINT16
    3: 2,   # INT16
    4: 4,   # UINT32
    5: 4,   # INT32
    6: 4,   # FLOAT32
    7: 1,   # BOOL
    10: 8,  # UINT64
    11: 8,  # INT64
    12: 8,  # FLOAT64
}
_STRING = 8
_ARRAY = 9

# struct format par type scalaire (little-endian).
_SCALAR_FMT = {
    0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
    6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d",
}

_MAGIC = b"GGUF"
# Garde-fou anti-corruption : une longueur de chaîne/array délirante (> 64 Mo /
# > 100M éléments) signale un offset cassé → on abandonne.
_MAX_STR = 64 * 1024 * 1024
_MAX_ARRAY = 100_000_000


@dataclass
class GgufMeta:
    architecture: str | None
    n_layers: int | None


def read_gguf_metadata(path: Path) -> GgufMeta | None:
    """Retourne (architecture, n_layers) ou `None` si illisible.

    `n_layers` provient de `<arch>.block_count`. On scanne les clés sans
    présupposer leur ordre : on garde `general.architecture` et la 1re clé
    se terminant par `.block_count`.
    """
    try:
        with path.open("rb") as f:
            if f.read(4) != _MAGIC:
                return None
            version = _u32(f)
            if version not in (2, 3):
                # v1 a un layout d'entiers différent ; on ne le supporte pas.
                return None
            _tensor_count = _u64(f)
            kv_count = _u64(f)
            if kv_count <= 0 or kv_count > 1_000_000:
                return None

            architecture: str | None = None
            n_layers: int | None = None

            for _ in range(kv_count):
                key = _read_string(f)
                vtype = _u32(f)
                want = key == "general.architecture" or key.endswith(".block_count")
                if want:
                    value = _read_typed(f, vtype)
                    if key == "general.architecture" and isinstance(value, str):
                        architecture = value
                    elif key.endswith(".block_count") and isinstance(value, int):
                        n_layers = value
                else:
                    _skip_value(f, vtype)
                if architecture is not None and n_layers is not None:
                    break

            return GgufMeta(architecture=architecture, n_layers=n_layers)
    except (OSError, EOFError, struct.error, ValueError):
        return None


# ---------------------------------------------------------------------------
# Primitives de lecture
# ---------------------------------------------------------------------------


def _read_exact(f: BinaryIO, n: int) -> bytes:
    b = f.read(n)
    if len(b) != n:
        raise EOFError("GGUF tronqué")
    return b


def _u32(f: BinaryIO) -> int:
    return struct.unpack("<I", _read_exact(f, 4))[0]


def _u64(f: BinaryIO) -> int:
    return struct.unpack("<Q", _read_exact(f, 8))[0]


def _read_string(f: BinaryIO) -> str:
    n = _u64(f)
    if n > _MAX_STR:
        raise ValueError(f"chaîne GGUF démesurée ({n})")
    return _read_exact(f, n).decode("utf-8", errors="replace")


def _read_typed(f: BinaryIO, vtype: int):  # noqa: ANN202 — retour union large
    """Lit une valeur scalaire/chaîne (les seules dont on extrait le contenu)."""
    if vtype == _STRING:
        return _read_string(f)
    if vtype in _SCALAR_FMT:
        fmt = _SCALAR_FMT[vtype]
        return struct.unpack(fmt, _read_exact(f, _SCALAR_SIZES[vtype]))[0]
    # Tableau ou type inattendu pour une clé recherchée : on consomme proprement
    # les octets et on renvoie None (la clé sera ignorée).
    _skip_value(f, vtype)
    return None


def _skip_value(f: BinaryIO, vtype: int) -> None:
    """Avance l'offset au-delà d'une valeur sans la matérialiser."""
    if vtype in _SCALAR_SIZES:
        f.seek(_SCALAR_SIZES[vtype], 1)
        return
    if vtype == _STRING:
        n = _u64(f)
        if n > _MAX_STR:
            raise ValueError(f"chaîne GGUF démesurée ({n})")
        f.seek(n, 1)
        return
    if vtype == _ARRAY:
        elem_type = _u32(f)
        count = _u64(f)
        if count > _MAX_ARRAY:
            raise ValueError(f"tableau GGUF démesuré ({count})")
        if elem_type in _SCALAR_SIZES:
            f.seek(_SCALAR_SIZES[elem_type] * count, 1)
        elif elem_type == _STRING:
            for _ in range(count):
                n = _u64(f)
                if n > _MAX_STR:
                    raise ValueError(f"chaîne GGUF démesurée ({n})")
                f.seek(n, 1)
        elif elem_type == _ARRAY:
            for _ in range(count):
                _skip_value(f, _ARRAY)
        else:
            raise ValueError(f"type d'élément GGUF inconnu ({elem_type})")
        return
    raise ValueError(f"type de valeur GGUF inconnu ({vtype})")
