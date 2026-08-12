import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient

from db import get_db
from main import app
from models import UserRoleEnum, User, UserSession
from services.sessions import create_session


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
    with patch("routes.auth.oauth.entra.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert "__Host-session" in response.cookies
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "samesite=strict" in cookie_header.lower()


@pytest.mark.asyncio
async def test_callback_rejects_unprovisioned_user(client, db_session):
    fake_token = {"userinfo": {"oid": "oid-x", "email": "nobody@smu.edu.sg"}}
    with patch("routes.auth.oauth.entra.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173/login?error=not_provisioned"
    assert "__Host-session" not in response.cookies
    result = await db_session.execute(select(UserSession))
    assert result.scalars().all() == []


def test_me_without_session_returns_401(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_with_valid_session_returns_user(client, db_session):
    user = User(id=uuid.uuid4(), email="loggedin@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)

    # SessionAuthMiddleware looks up the cookie via the module-level
    # db.async_session (real Postgres), not the overridden get_db
    # dependency used by route handlers. Point it at the same sqlite
    # fixture session so the middleware sees the row we just created.
    @asynccontextmanager
    async def fake_async_session():
        yield db_session

    with patch("auth.middleware.async_session", fake_async_session):
        client.cookies.set("__Host-session", raw_token)
        response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {"email": "loggedin@smu.edu.sg", "role": "instructor"}


@pytest.mark.asyncio
async def test_stale_cookie_on_auth_path_falls_through(client, db_session):
    # A stale or invalid session cookie under /api/auth/* shouldn't hard-401,
    # that would lock the user out of the very flow meant to fix it. It
    # should just fall through as anonymous and let the route run normally.
    @asynccontextmanager
    async def fake_async_session():
        yield db_session

    fake_token = {"userinfo": {"oid": "oid-stale", "email": "stale@smu.edu.sg"}}
    with patch("auth.middleware.async_session", fake_async_session), patch(
        "routes.auth.oauth.entra.authorize_access_token", new=AsyncMock(return_value=fake_token)
    ):
        client.cookies.set("__Host-session", "not-a-real-token")
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code != 401


@pytest.mark.asyncio
async def test_stale_cookie_on_non_auth_path_returns_401(client, db_session):
    # Outside /api/auth/*, a stale/invalid cookie should never happen for a
    # legitimate client and must fail fast rather than silently falling
    # through as anonymous.
    @asynccontextmanager
    async def fake_async_session():
        yield db_session

    with patch("auth.middleware.async_session", fake_async_session):
        client.cookies.set("__Host-session", "not-a-real-token")
        response = client.get("/health")

    assert response.status_code == 401
