import uuid
from unittest.mock import AsyncMock, patch

import pytest
from authlib.integrations.base_client.errors import OAuthError
from fastapi.testclient import TestClient
from sqlalchemy import select

from config import FRONTEND_URL
from db import get_db
from main import app
from models import User, UserRoleEnum, UserSession
from services import create_session


@pytest.fixture
def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_callback_creates_session_for_provisioned_user(client, db_session):
    user = User(id=uuid.uuid4(), email="prov@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    fake_token = {"userinfo": {"oid": "oid-prov", "email": "prov@smu.edu.sg"}}
    with patch("routes.auth_routes.oauth.entra.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert "__Host-session" in response.cookies
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "samesite=strict" in cookie_header.lower()


@pytest.mark.asyncio
async def test_callback_signs_in_when_entra_sends_a_different_email_case(client, db_session):
    # End to end version of the provisioning-case bug: the row is correct, the
    # person is real, and the only difference is capitalisation in the claim.
    # This used to land on /login?error=not_provisioned.
    user = User(id=uuid.uuid4(), email="ada@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    fake_token = {"userinfo": {"oid": "oid-ada", "email": "Ada@SMU.edu.sg"}}
    with patch("routes.auth_routes.oauth.entra.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == FRONTEND_URL
    assert "__Host-session" in response.cookies


@pytest.mark.asyncio
async def test_callback_redirects_unprovisioned_user(client, db_session):
    fake_token = {"userinfo": {"oid": "oid-x", "email": "nobody@smu.edu.sg"}}
    with patch("routes.auth_routes.oauth.entra.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"{FRONTEND_URL}/login?error=not_provisioned"
    assert "__Host-session" not in response.cookies
    result = await db_session.execute(select(UserSession))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_callback_issues_no_session_on_attempted_account_takeover(client, db_session):
    victim = User(
        id=uuid.uuid4(),
        email="victim@smu.edu.sg",
        entra_oid="victim-oid",
        role=UserRoleEnum.root_admin,
    )
    db_session.add(victim)
    await db_session.commit()

    attacker = {"userinfo": {"oid": "attacker-oid", "email": "victim@smu.edu.sg"}}
    with patch("routes.auth_routes.oauth.entra.authorize_access_token", new=AsyncMock(return_value=attacker)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"{FRONTEND_URL}/login?error=not_provisioned"
    assert "__Host-session" not in response.cookies
    assert (await db_session.execute(select(UserSession))).scalars().all() == []
    await db_session.refresh(victim)
    assert victim.entra_oid == "victim-oid"


def test_me_without_session_returns_401(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_with_valid_session_returns_user(client, db_session):
    user = User(id=uuid.uuid4(), email="loggedin@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)
    client.cookies.set("__Host-session", raw_token)
    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {"email": "loggedin@smu.edu.sg", "role": "instructor"}


def test_callback_sends_a_cancelled_sign_in_to_the_spa_login(client):
    # Regression: this used to redirect to /api/auth/login, which re-enters the
    # Entra redirect immediately - a user who cancelled was thrown back at the
    # prompt they had just dismissed and could never reach our own login page.
    error = OAuthError(error="access_denied", description="user cancelled")
    with patch("routes.auth_routes.oauth.entra.authorize_access_token", new=AsyncMock(side_effect=error)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"{FRONTEND_URL}/login?error=sign_in_cancelled"
    assert "__Host-session" not in response.cookies


def test_callback_sends_any_other_oauth_failure_to_the_spa_login(client):
    error = OAuthError(error="mismatching_state", description="CSRF Warning!")
    with patch("routes.auth_routes.oauth.entra.authorize_access_token", new=AsyncMock(side_effect=error)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"{FRONTEND_URL}/login?error=sign_in_failed"
    assert "__Host-session" not in response.cookies


def test_callback_never_redirects_back_into_the_entra_flow(client):
    # The loop guard. No callback failure may point the browser at a URL that
    # restarts the OIDC redirect - the user must always land somewhere with a
    # way out.
    for error in (
        OAuthError(error="access_denied", description="user cancelled"),
        OAuthError(error="mismatching_state", description="CSRF Warning!"),
        OAuthError(description='Missing "state" parameter'),
    ):
        with patch("routes.auth_routes.oauth.entra.authorize_access_token", new=AsyncMock(side_effect=error)):
            response = client.get("/api/auth/callback", follow_redirects=False)

        assert "/api/auth/login" not in response.headers["location"]
        assert response.headers["location"].startswith(f"{FRONTEND_URL}/login?error=")


def test_callback_does_not_reflect_entra_error_text_into_the_url(client):
    # error_description is provider-controlled. It must never reach a URL the
    # browser lands on.
    error = OAuthError(error="invalid_client", description="<script>alert(1)</script>")
    with patch("routes.auth_routes.oauth.entra.authorize_access_token", new=AsyncMock(side_effect=error)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    location = response.headers["location"]
    assert "script" not in location
    assert "invalid_client" not in location
    assert location == f"{FRONTEND_URL}/login?error=sign_in_failed"


@pytest.mark.asyncio
async def test_callback_ignores_stale_cookie(client, db_session):
    fake_token = {"userinfo": {"oid": "oid-stale", "email": "stale@smu.edu.sg"}}
    with patch("routes.auth_routes.oauth.entra.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        client.cookies.set("__Host-session", "not-a-real-token")
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code != 401


def test_stale_cookie_on_protected_route_returns_401(client):
    client.cookies.set("__Host-session", "not-a-real-token")
    response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_entra_routes_are_always_mounted():
    assert {"/api/auth/login", "/api/auth/callback"} <= set(app.openapi()["paths"])


def test_no_password_less_dev_login_exists(client):
    assert not [path for path in app.openapi()["paths"] if "/dev" in path]
    assert client.post("/api/auth/dev/login", json={"email": "a@b.c"}).status_code == 404
    assert client.get("/api/auth/dev/users").status_code == 404
