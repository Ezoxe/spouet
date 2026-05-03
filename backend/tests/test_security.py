from spouet.core.security import generate_token, hash_token, verify_token


def test_generate_token_unique() -> None:
    a = generate_token()
    b = generate_token()
    assert a != b
    assert len(a) > 30


def test_hash_token_deterministic() -> None:
    t = "abcdef"
    assert hash_token(t) == hash_token(t)
    assert len(hash_token(t)) == 64  # sha256 hex


def test_verify_token_roundtrip() -> None:
    t = generate_token()
    assert verify_token(t, hash_token(t))
    assert not verify_token(t + "x", hash_token(t))
