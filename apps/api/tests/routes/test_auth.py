import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient

from config import ENTRA_CONFIGURED
from db import get_db
from main import app
from models import UserRoleEnum, User, UserSession
from services.sessions import create_session

needs_entra = pytest.mark.skipif(
    not ENTRA_CONFIGURED,
    reason="Entra routes aren't mounted without an app registration configured",
)


@pytest.fixture
def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@needs_entra
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


@needs_entra
@pytest.mark.asyncio
async def test_callback_rejects_unprovisioned_user(client, db_session):
    fake_token = {"userinfo": {"oid": "oid-x", "email": "nobody@smu.edu.sg"}}
    with patch("routes.auth.oauth.entra.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 403
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

    @asynccontextmanager
    async def fake_async_session():
        yield db_session

    with patch("auth.middleware.async_session", fake_async_session):
        client.cookies.set("__Host-session", raw_token)
        response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {"email": "loggedin@smu.edu.sg", "role": "instructor"}


@needs_entra
@pytest.mark.asyncio
async def test_stale_cookie_on_auth_path_falls_through(client, db_session):
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
    @asynccontextmanager
    async def fake_async_session():
        yield db_session

    with patch("auth.middleware.async_session", fake_async_session):
        client.cookies.set("__Host-session", "not-a-real-token")
        response = client.get("/health")

    assert response.status_code == 401


def test_entra_routes_mounted_only_when_configured():
    entra_paths = {"/api/auth/login", "/api/auth/callback"} & set(app.openapi()["paths"])
    assert entra_paths == (
        {"/api/auth/login", "/api/auth/callback"} if ENTRA_CONFIGURED else set()
    )
