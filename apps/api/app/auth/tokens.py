import hashlib
import secrets


def generate_session_token() -> str:
    """256-bit random session id, sent to the browser as the cookie value.
    We never store this raw server-side, only its hash (see hash_token)."""
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    # Store only the hash so a leaked sessions table row can't be replayed
    # as a cookie, same idea as hashing passwords.
    return hashlib.sha256(raw_token.encode()).hexdigest()
