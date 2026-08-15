import uuid
from datetime import UTC

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from config import DEV_AUTH_ENABLED, resolve_dev_auth_enabled
from db import get_db
from main import app as main_app
from models import User, UserRoleEnum, UserSession
from routes.dev_auth import router as dev_auth_router


@pytest.fixture
def dev_client(db_session, monkeypatch):
    # main.app only mounts this router when DEV_AUTH_ENABLED, and CI runs
    # without that set, so mount it on a bare app here instead of reaching for
    # environment reloads. The flag is patched because the router's own
    # dependency re-checks it on every request.
    monkeypatch.setattr("routes.dev_auth.DEV_AUTH_ENABLED", True)

    async def override_get_db():
        yield db_session

    app = FastAPI()
    app.include_router(dev_auth_router)
    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


@pytest.mark.asyncio
async def test_dev_login_creates_session_for_provisioned_user(dev_client, db_session):
    user = User(id=uuid.uuid4(), email="dev@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    response = dev_client.post("/api/auth/dev/login", json={"email": "dev@smu.edu.sg"})

    assert response.status_code == 204
    cookie_header = response.headers["set-cookie"]
    # Same cookie hardening as the Entra callback - a dev session is an
    # ordinary session, only its provenance differs.
    assert "__Host-session" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "samesite=strict" in cookie_header.lower()

    result = await db_session.execute(select(UserSession).where(UserSession.user_id == user.id))
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_dev_login_rejects_unprovisioned_email(dev_client, db_session):
    response = dev_client.post("/api/auth/dev/login", json={"email": "nobody@smu.edu.sg"})

    assert response.status_code == 403
    result = await db_session.execute(select(UserSession))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_dev_login_rejects_soft_deleted_user(dev_client, db_session):
    from datetime import datetime

    user = User(
        id=uuid.uuid4(),
        email="gone@smu.edu.sg",
        role=UserRoleEnum.instructor,
        deleted_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.commit()

    response = dev_client.post("/api/auth/dev/login", json={"email": "gone@smu.edu.sg"})

    assert response.status_code == 403
    result = await db_session.execute(select(UserSession))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_dev_login_ignores_role_in_request_body(dev_client, db_session):
    # The whole point of the dev path is that it skips authentication, not
    # authorization. A caller must not be able to pick their own role.
    user = User(id=uuid.uuid4(), email="ta@smu.edu.sg", role=UserRoleEnum.teaching_assistant)
    db_session.add(user)
    await db_session.commit()

    response = dev_client.post(
        "/api/auth/dev/login",
        json={"email": "ta@smu.edu.sg", "role": "root_admin"},
    )

    assert response.status_code == 204
    await db_session.refresh(user)
    assert user.role is UserRoleEnum.teaching_assistant


@pytest.mark.asyncio
async def test_dev_users_lists_only_live_accounts(dev_client, db_session):
    from datetime import datetime

    db_session.add_all(
        [
            User(id=uuid.uuid4(), email="live@smu.edu.sg", role=UserRoleEnum.instructor),
            User(
                id=uuid.uuid4(),
                email="deleted@smu.edu.sg",
                role=UserRoleEnum.instructor,
                deleted_at=datetime.now(UTC),
            ),
        ]
    )
    await db_session.commit()

    response = dev_client.get("/api/auth/dev/users")

    assert response.status_code == 200
    emails = [u["email"] for u in response.json()["users"]]
    assert emails == ["live@smu.edu.sg"]


def test_dev_routes_404_when_flag_is_off(dev_client, monkeypatch):
    # Even mounted, the router's dependency keeps the paths dead unless the
    # flag is on, so a refactor that mounts it unconditionally stays safe.
    monkeypatch.setattr("routes.dev_auth.DEV_AUTH_ENABLED", False)

    assert dev_client.get("/api/auth/dev/users").status_code == 404
    assert dev_client.post("/api/auth/dev/login", json={"email": "a@b.c"}).status_code == 404


def test_dev_routes_mounted_only_when_flag_is_set():
    # Gate 2: the paths exist on the real app if and only if the flag is on.
    # Asserted against whatever config resolved to, so this holds both in CI
    # (no flag) and on a developer's box with dev login switched on.
    # Read through the OpenAPI schema rather than app.routes: FastAPI keeps
    # included routers lazy, so app.routes doesn't flatten to concrete paths.
    dev_paths = {path for path in main_app.openapi()["paths"] if path.startswith("/api/auth/dev")}
    assert dev_paths == ({"/api/auth/dev/login", "/api/auth/dev/users"} if DEV_AUTH_ENABLED else set())


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_dev_auth_flag_is_rejected_outside_dev(environment):
    with pytest.raises(ValueError, match="ENVIRONMENT"):
        resolve_dev_auth_enabled("true", environment)


def test_dev_auth_flag_allowed_in_dev():
    assert resolve_dev_auth_enabled("true", "dev") is True
    assert resolve_dev_auth_enabled(None, "dev") is False
    assert resolve_dev_auth_enabled("false", "dev") is False


@pytest.mark.parametrize("environment", ["dev", "prod"])
def test_dev_auth_flag_rejects_unparseable_values(environment):
    # A typo must not silently resolve either way.
    with pytest.raises(ValueError, match="DEV_AUTH_ENABLED"):
        resolve_dev_auth_enabled("ture", environment)
