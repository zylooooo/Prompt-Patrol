from auth.tokens import generate_session_token, hash_token


def test_generate_session_token_is_url_safe_and_long():
    token = generate_session_token()
    assert len(token) >= 32
    assert all(c.isalnum() or c in "-_" for c in token)


def test_hash_token_is_deterministic_and_sha256_length():
    token = "abc123"
    digest = hash_token(token)
    assert digest == hash_token(token)
    assert len(digest) == 64  # hex-encoded sha256


def test_generate_session_token_is_unique_per_call():
    assert generate_session_token() != generate_session_token()
