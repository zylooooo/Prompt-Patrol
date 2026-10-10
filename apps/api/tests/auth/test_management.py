import re

import httpx
import pytest

import auth.management as management
from exceptions import Auth0ProvisioningError


def _fake_auth0(monkeypatch, create_statuses):
    """Swaps the Auth0 client for a fake one. POST /api/v2/users answers with
    each of `create_statuses` in turn; returns the list of paths called."""
    calls = []
    statuses = iter(create_statuses)

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        if request.url.path == "/api/v2/users":
            status = next(statuses)
            if status == 201:
                return httpx.Response(201, json={"user_id": "auth0|new"})
            return httpx.Response(status, json={"message": "The user already exists."})
        return httpx.Response(200)  # change_password, DELETE

    client = httpx.AsyncClient(base_url="https://auth0.test", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(management, "_client", client)
    monkeypatch.setattr(management, "_token", None)
    monkeypatch.setattr(management, "_CREATE_RETRY_DELAY_SECONDS", 0)
    return calls


@pytest.mark.asyncio
async def test_the_management_token_is_fetched_once_and_reused(monkeypatch):
    calls = _fake_auth0(monkeypatch, [201, 201])
    await management.invite_user("a@example.com")
    await management.invite_user("b@example.com")
    await management.delete_auth0_user("auth0|new")
    assert calls.count("/oauth/token") == 1


@pytest.mark.asyncio
async def test_an_expired_token_is_fetched_again(monkeypatch):
    calls = _fake_auth0(monkeypatch, [201])
    monkeypatch.setattr(management, "_token", ("old", 0.0))
    await management.invite_user("a@example.com")
    assert calls.count("/oauth/token") == 1


@pytest.mark.asyncio
async def test_a_409_right_after_a_delete_is_retried(monkeypatch):
    """Re-provisioning a just-deleted email: Auth0 briefly still has it."""
    calls = _fake_auth0(monkeypatch, [409, 201])
    assert await management.invite_user("a@example.com") == "auth0|new"
    assert calls.count("/api/v2/users") == 2


@pytest.mark.asyncio
async def test_a_409_that_never_clears_fails_with_auth0s_reason(monkeypatch):
    calls = _fake_auth0(monkeypatch, [409] * management._CREATE_ATTEMPTS)
    with pytest.raises(Auth0ProvisioningError, match="409.*already exists"):
        await management.invite_user("a@example.com")
    assert calls.count("/api/v2/users") == management._CREATE_ATTEMPTS


def test_the_placeholder_password_always_meets_auth0s_strictest_policy():
    """Auth0's "Excellent" policy: all four character classes, no character
    three times in a row. Random output, so check plenty of samples."""
    for _ in range(2000):
        password = management._placeholder_password()
        assert re.search(r"[a-z]", password) and re.search(r"[A-Z]", password)
        assert re.search(r"[0-9]", password) and re.search(r"[^A-Za-z0-9]", password)
        assert not re.search(r"(.)\1\1", password)
