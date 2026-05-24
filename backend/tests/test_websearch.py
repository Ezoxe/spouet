"""Tests du parsing SearXNG (fonctions pures, sans réseau ni Redis)."""

from __future__ import annotations

from spouet.websearch.client import _parse_answer, _parse_results


_WEB_SAMPLE = {
    "results": [
        {
            "url": "https://lol.fandom.com/wiki/Nidalee",
            "title": "Nidalee - counters",
            "content": "Les meilleurs counters de Nidalee jungle sont...",
            "engine": "duckduckgo",
        },
        {
            "url": "https://example.com/no-title",
            "title": "",
            "content": "snippet sans titre",
        },
        {"not": "a dict"},
        {"title": "", "url": ""},  # ignoré
    ],
    "answers": ["Nidalee est counter par les junglers à fort early."],
    "infoboxes": [],
}

_IMAGE_SAMPLE = {
    "results": [
        {
            "url": "https://img.example/page",
            "title": "Nidalee splash",
            "img_src": "https://img.example/nidalee.jpg",
            "thumbnail_src": "https://img.example/nidalee_thumb.jpg",
        }
    ]
}


def test_parse_web_results_filters_empty_and_caps_count():
    out = _parse_results(_WEB_SAMPLE, kind="web", count=10)
    # 2 valides (le dict non-dict et l'entrée vide sont écartés)
    assert len(out) == 2
    assert out[0].title == "Nidalee - counters"
    assert out[0].url.startswith("https://lol.fandom.com")
    assert out[0].snippet.startswith("Les meilleurs")
    # Pas d'image en mode web
    assert out[0].image is None
    # Titre vide → on retombe sur l'URL
    assert out[1].title == "https://example.com/no-title"


def test_parse_results_respects_count():
    out = _parse_results(_WEB_SAMPLE, kind="web", count=1)
    assert len(out) == 1


def test_parse_image_results_extracts_img_src():
    out = _parse_results(_IMAGE_SAMPLE, kind="images", count=6)
    assert len(out) == 1
    assert out[0].image == "https://img.example/nidalee.jpg"
    assert out[0].thumbnail == "https://img.example/nidalee_thumb.jpg"


def test_parse_answer_prefers_string_answers():
    assert _parse_answer(_WEB_SAMPLE) == "Nidalee est counter par les junglers à fort early."


def test_parse_answer_falls_back_to_infobox():
    data = {"answers": [], "infoboxes": [{"content": "Une infobox utile."}]}
    assert _parse_answer(data) == "Une infobox utile."


def test_parse_answer_none_when_absent():
    assert _parse_answer({"results": []}) is None
