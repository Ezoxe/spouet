"""Tests du lecteur d'en-tête GGUF (gguf_meta) — extraction de block_count.

On fabrique des en-têtes GGUF minimaux en mémoire (sans tenseurs) et on vérifie
que l'architecture + le nombre de couches sont lus, que les clés non pertinentes
(y compris des tableaux) sont correctement sautées, et que tout fichier illisible
retombe sur None (→ l'appelant garde n_gpu_layers=-1).
"""

from __future__ import annotations

import struct

from spouet_agent.gguf_meta import read_gguf_metadata


def _gstr(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def _kv_string(key: str, val: str) -> bytes:
    return _gstr(key) + struct.pack("<I", 8) + _gstr(val)


def _kv_u32(key: str, val: int) -> bytes:
    return _gstr(key) + struct.pack("<I", 4) + struct.pack("<I", val)


def _kv_array_u32(key: str, vals: list[int]) -> bytes:
    out = _gstr(key) + struct.pack("<I", 9) + struct.pack("<I", 4) + struct.pack("<Q", len(vals))
    for v in vals:
        out += struct.pack("<I", v)
    return out


def _build_gguf(kvs: list[bytes], version: int = 3) -> bytes:
    header = b"GGUF" + struct.pack("<I", version) + struct.pack("<Q", 0) + struct.pack("<Q", len(kvs))
    return header + b"".join(kvs)


def test_reads_architecture_and_block_count(tmp_path):
    # Un tableau placé AVANT block_count vérifie que le saut d'array est correct.
    data = _build_gguf([
        _kv_string("general.architecture", "llama"),
        _kv_array_u32("llama.attention.head_count_kv", [8, 8, 8]),
        _kv_string("general.name", "Test 8B"),
        _kv_u32("llama.block_count", 32),
    ])
    p = tmp_path / "model.gguf"
    p.write_bytes(data)

    meta = read_gguf_metadata(p)
    assert meta is not None
    assert meta.architecture == "llama"
    assert meta.n_layers == 32


def test_missing_block_count(tmp_path):
    data = _build_gguf([_kv_string("general.architecture", "qwen2")])
    p = tmp_path / "m.gguf"
    p.write_bytes(data)
    meta = read_gguf_metadata(p)
    assert meta is not None
    assert meta.architecture == "qwen2"
    assert meta.n_layers is None


def test_not_a_gguf(tmp_path):
    p = tmp_path / "bad.gguf"
    p.write_bytes(b"NOTGGUF\x00\x00\x00\x00")
    assert read_gguf_metadata(p) is None


def test_truncated_header(tmp_path):
    p = tmp_path / "trunc.gguf"
    # Magic + version mais tronqué avant les compteurs → EOFError → None.
    p.write_bytes(b"GGUF" + struct.pack("<I", 3) + b"\x01\x02")
    assert read_gguf_metadata(p) is None


def test_missing_file(tmp_path):
    assert read_gguf_metadata(tmp_path / "nope.gguf") is None
