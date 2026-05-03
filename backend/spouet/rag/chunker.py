"""Chunker simple par fenêtre de mots avec recouvrement."""

from __future__ import annotations

import re
from dataclasses import dataclass

from spouet.orchestrator.context import estimate_tokens

# Heuristique : split sur paragraphes / phrases pour respecter la sémantique
PARA_SPLIT = re.compile(r"\n\s*\n")


@dataclass
class Chunk:
    idx: int
    text: str
    tokens: int


def chunk_text(text: str, *, target_tokens: int = 350, overlap_tokens: int = 50) -> list[Chunk]:
    """Split sur paragraphes puis fusionne en blocs ~target_tokens.

    overlap_tokens : ajoute la fin du chunk précédent au début du suivant.
    """
    text = text.strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in PARA_SPLIT.split(text) if p.strip()]
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_tokens = 0
    overlap_chars = overlap_tokens * 4

    def flush() -> None:
        nonlocal buf, buf_tokens
        if not buf:
            return
        joined = "\n\n".join(buf).strip()
        if joined:
            chunks.append(Chunk(idx=len(chunks), text=joined, tokens=estimate_tokens(joined)))
        buf = []
        buf_tokens = 0

    for para in paragraphs:
        ptokens = estimate_tokens(para)
        if ptokens > target_tokens * 1.5:
            # Paragraphe géant : split mécanique sur phrases
            for sub in _split_long(para, target_tokens):
                if buf_tokens + estimate_tokens(sub) > target_tokens and buf:
                    flush()
                    if chunks and overlap_chars:
                        buf = [chunks[-1].text[-overlap_chars:]]
                        buf_tokens = estimate_tokens(buf[0])
                buf.append(sub)
                buf_tokens += estimate_tokens(sub)
            continue

        if buf_tokens + ptokens > target_tokens and buf:
            flush()
            if chunks and overlap_chars:
                buf = [chunks[-1].text[-overlap_chars:]]
                buf_tokens = estimate_tokens(buf[0])
        buf.append(para)
        buf_tokens += ptokens

    flush()
    return chunks


def _split_long(text: str, target: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out: list[str] = []
    cur: list[str] = []
    cur_tokens = 0
    for s in sentences:
        st = estimate_tokens(s)
        if cur_tokens + st > target and cur:
            out.append(" ".join(cur))
            cur = []
            cur_tokens = 0
        cur.append(s)
        cur_tokens += st
    if cur:
        out.append(" ".join(cur))
    return out
