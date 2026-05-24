"""Recherche web rapide via SearXNG self-hosted (in-process, pas de conteneur).

Pourquoi in-process et pas un tool Docker : la latence de spin-up d'un conteneur
(plusieurs centaines de ms à plusieurs secondes) tuerait l'objectif « le plus
rapide possible ». Un appel httpx async direct + cache Redis court répond en
~1 s, et le second appel sur la même requête est quasi-instantané.

SearXNG n'est jamais exposé au LAN (service interne docker-compose). L'API
``search()`` est volontairement abstraite pour permettre de swapper vers une API
hostée (Brave/Tavily) plus tard sans toucher les appelants.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import httpx
import redis.asyncio as redis

from spouet.core.config import settings
from spouet.core.logging import get_logger

logger = get_logger(__name__)

SearchKind = Literal["web", "images"]


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    image: str | None = None  # img_src plein format (kind=images)
    thumbnail: str | None = None
    engine: str | None = None


@dataclass
class SearchResponse:
    query: str
    kind: str
    results: list[SearchResult] = field(default_factory=list)
    # Réponse directe extraite des `answers`/`infoboxes` SearXNG (Wikipedia,
    # calculatrice, etc.) — quand elle existe, l'IA peut répondre sans lire les
    # snippets.
    answer: str | None = None


def _cache_key(query: str, kind: str, lang: str) -> str:
    h = hashlib.sha256(f"{kind}|{lang}|{query.lower().strip()}".encode()).hexdigest()[:32]
    return f"websearch:{h}"


async def _cache_get(key: str) -> SearchResponse | None:
    cli = redis.from_url(str(settings.redis_url), decode_responses=True)
    try:
        raw = await cli.get(key)
    except Exception:  # noqa: BLE001 — un cache HS ne doit pas casser la recherche
        return None
    finally:
        await cli.aclose()
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return SearchResponse(
            query=d["query"],
            kind=d["kind"],
            answer=d.get("answer"),
            results=[SearchResult(**r) for r in d.get("results", [])],
        )
    except Exception:  # noqa: BLE001
        return None


async def _cache_set(key: str, resp: SearchResponse) -> None:
    cli = redis.from_url(str(settings.redis_url), decode_responses=True)
    try:
        payload = {
            "query": resp.query,
            "kind": resp.kind,
            "answer": resp.answer,
            "results": [asdict(r) for r in resp.results],
        }
        await cli.set(key, json.dumps(payload, ensure_ascii=False), ex=settings.websearch_cache_ttl_s)
    except Exception:  # noqa: BLE001
        pass
    finally:
        await cli.aclose()


def _parse_results(data: dict[str, Any], *, kind: str, count: int) -> list[SearchResult]:
    out: list[SearchResult] = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or item.get("img_src") or "").strip()
        title = (item.get("title") or "").strip()
        if not url and not title:
            continue
        out.append(
            SearchResult(
                title=title or url,
                url=url,
                snippet=(item.get("content") or "").strip(),
                image=(item.get("img_src") or None) if kind == "images" else None,
                thumbnail=item.get("thumbnail_src") or item.get("thumbnail") or None,
                engine=item.get("engine"),
            )
        )
        if len(out) >= count:
            break
    return out


def _parse_answer(data: dict[str, Any]) -> str | None:
    for a in data.get("answers") or []:
        if isinstance(a, str) and a.strip():
            return a.strip()
        if isinstance(a, dict):
            txt = (a.get("answer") or a.get("content") or "").strip()
            if txt:
                return txt
    for ib in data.get("infoboxes") or []:
        if isinstance(ib, dict):
            txt = (ib.get("content") or "").strip()
            if txt:
                return txt
    return None


async def search(
    query: str, *, kind: SearchKind = "web", count: int = 6, lang: str = "fr"
) -> SearchResponse:
    """Recherche ``query`` sur SearXNG. ``kind`` ∈ {web, images}.

    Ne lève jamais : en cas d'échec réseau / SearXNG indisponible, renvoie une
    réponse vide (l'IA dira qu'elle n'a pas trouvé). Met le résultat en cache.
    """
    query = (query or "").strip()
    if not query or not settings.websearch_enabled:
        return SearchResponse(query=query, kind=kind)

    cache_key = _cache_key(query, kind, lang)
    cached = await _cache_get(cache_key)
    if cached is not None:
        return cached

    params = {
        "q": query,
        "format": "json",
        "language": lang,
        "categories": "images" if kind == "images" else "general",
        "safesearch": "1",
    }
    base = str(settings.searxng_url).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=settings.websearch_timeout_s) as client:
            r = await client.get(
                f"{base}/search", params=params, headers={"User-Agent": "Spouet/1.0"}
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("websearch.failed", error=str(e), kind=kind)
        return SearchResponse(query=query, kind=kind)

    if not isinstance(data, dict):
        return SearchResponse(query=query, kind=kind)

    resp = SearchResponse(
        query=query,
        kind=kind,
        results=_parse_results(data, kind=kind, count=count),
        answer=_parse_answer(data),
    )
    await _cache_set(cache_key, resp)
    return resp
