"""Tests crypto + secrets store (sans DB)."""

from __future__ import annotations

from spouet.core.crypto import decrypt, encrypt
from spouet.secrets.store import SecretRef, preview


def test_encrypt_decrypt_roundtrip() -> None:
    msg = "ceci est un mot de passe & spécial=42"
    ct = encrypt(msg)
    assert ct != msg
    assert decrypt(ct) == msg


def test_encrypt_is_not_deterministic() -> None:
    a = encrypt("hello")
    b = encrypt("hello")
    # Fernet inclut un IV aléatoire ; deux chiffrements de la même valeur diffèrent
    assert a != b
    assert decrypt(a) == decrypt(b) == "hello"


def test_secret_ref_parse() -> None:
    r = SecretRef.parse("connector:discord-bot/token")
    assert r.scope == "connector:discord-bot"
    assert r.key == "token"
    assert r.as_str() == "connector:discord-bot/token"


def test_secret_ref_parse_invalid() -> None:
    import pytest

    with pytest.raises(ValueError):
        SecretRef.parse("no-slash")
    with pytest.raises(ValueError):
        SecretRef.parse("/missing-scope")


def test_preview_masks_value() -> None:
    p = preview("supersecretvalue")
    assert p.startswith("sup")
    assert "•" in p
    assert "supersecret" not in p
