import uuid
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import pytest
from authlib.integrations.base_client.errors import OAuthError
from fastapi.testclient import TestClient
from sqlalchemy import select

from config import FRONTEND_URL
from db import get_db
from main import app
from models import User, UserRoleEnum, UserSession
from services import authenticate_session, create_session


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


@pytest.mark.asyncio
async def test_identity_header_alone_does_not_authenticate(client, db_session):
    # The gateway-header bypass. get_current_user used to accept X-PP-User-Id as
    # proof of identity whenever ENVIRONMENT was not "dev", with no cookie and no
    # session lookup - so any live user id was a full login for that account, and
    # nginx forwarded the header from the client untouched.
    user = User(id=uuid.uuid4(), email="target@smu.edu.sg", role=UserRoleEnum.root_admin)
    db_session.add(user)
    await db_session.commit()

    response = client.get("/api/auth/me", headers={"X-PP-User-Id": str(user.id)})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_identity_header_cannot_override_the_session_cookie(client, db_session):
    # A valid session plus a header naming someone else must resolve to the
    # cookie's owner, never the header's.
    owner = User(id=uuid.uuid4(), email="owner@smu.edu.sg", role=UserRoleEnum.teaching_assistant)
    other = User(id=uuid.uuid4(), email="other@smu.edu.sg", role=UserRoleEnum.root_admin)
    db_session.add_all([owner, other])
    await db_session.commit()
    raw_token = await create_session(db_session, owner.id)

    client.cookies.set("__Host-session", raw_token)
    response = client.get("/api/auth/me", headers={"X-PP-User-Id": str(other.id)})

    assert response.status_code == 200
    assert response.json() == {"email": "owner@smu.edu.sg", "role": "teaching_assistant"}


def test_no_gateway_header_trust_remains_in_the_auth_dependency():
    # Guards the shape, not just the behaviour: authentication must not branch on
    # the environment, or the bypass returns the moment ENVIRONMENT changes.
    # Inspects the executable body only - the docstring deliberately names the
    # removed header so the next reader knows why it must not come back.
    import ast
    import inspect
    import textwrap

    from auth import dependencies

    function = ast.parse(textwrap.dedent(inspect.getsource(dependencies.get_current_user))).body[0]
    body = function.body
    if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    code = "\n".join(ast.unparse(node) for node in body)

    assert "X-PP-User-Id" not in code
    assert "ENVIRONMENT" not in code


def test_entra_routes_are_always_mounted():
    assert {"/api/auth/login", "/api/auth/callback"} <= set(app.openapi()["paths"])


def test_no_password_less_dev_login_exists(client):
    assert not [path for path in app.openapi()["paths"] if "/dev" in path]
    assert client.post("/api/auth/dev/login", json={"email": "a@b.c"}).status_code == 404
    assert client.get("/api/auth/dev/users").status_code == 404


# --- sign-out ---------------------------------------------------------------
# Logout had no tests at all before 2026-08-16, despite being the route with the
# most side effects: it revokes a row, clears a cookie, and hands the browser to
# a third party.

END_SESSION = "https://login.microsoftonline.com/tid/oauth2/v2.0/logout"


def _discovery(monkeypatch_target="routes.auth_routes.oauth.entra.load_server_metadata"):
    return patch(monkeypatch_target, new=AsyncMock(return_value={"end_session_endpoint": END_SESSION}))


async def _signed_in_client(client, db_session, **user_kwargs):
    user = User(id=uuid.uuid4(), email="out@smu.edu.sg", role=UserRoleEnum.instructor, **user_kwargs)
    db_session.add(user)
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)
    client.cookies.set("__Host-session", raw_token)
    return user, raw_token


@pytest.mark.asyncio
async def test_logout_revokes_the_session(client, db_session):
    user, raw_token = await _signed_in_client(client, db_session)

    with _discovery():
        response = client.post("/api/auth/logout", follow_redirects=False)

    assert response.status_code == 303
    assert await authenticate_session(db_session, raw_token) is None


@pytest.mark.asyncio
async def test_logout_clears_the_cookie_with_matching_attributes(client, db_session):
    # delete_cookie must repeat path/secure/httponly/samesite or the browser
    # keeps the original cookie and the user stays signed in locally.
    await _signed_in_client(client, db_session)

    with _discovery():
        response = client.post("/api/auth/logout", follow_redirects=False)

    header = response.headers["set-cookie"]
    assert "__Host-session=" in header
    assert "Path=/" in header
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "samesite=strict" in header.lower()


@pytest.mark.asyncio
async def test_logout_uses_the_discovered_end_session_endpoint(client, db_session):
    # Not a hardcoded login.microsoftonline.com URL - the endpoint comes from the
    # provider's own metadata, which is what makes non-global Azure clouds work.
    await _signed_in_client(client, db_session)

    with _discovery():
        response = client.post("/api/auth/logout", follow_redirects=False)

    location = response.headers["location"]
    assert location.startswith(END_SESSION)
    assert quote(FRONTEND_URL, safe="") in location.replace("%2F", "%2F")


@pytest.mark.asyncio
async def test_logout_sends_logout_hint_when_one_was_captured(client, db_session):
    # Without this parameter Entra asks "which account do you want to sign out
    # from?" instead of just signing the user out.
    await _signed_in_client(client, db_session, logout_hint="opaque-hint-from-entra")

    with _discovery():
        response = client.post("/api/auth/logout", follow_redirects=False)

    assert "logout_hint=opaque-hint-from-entra" in response.headers["location"]


@pytest.mark.asyncio
async def test_logout_omits_logout_hint_when_none_was_captured(client, db_session):
    # The optional claim may not be enabled on the app registration. That
    # degrades to the account picker; it must not break sign-out.
    await _signed_in_client(client, db_session)

    with _discovery():
        response = client.post("/api/auth/logout", follow_redirects=False)

    assert response.status_code == 303
    assert "logout_hint" not in response.headers["location"]


@pytest.mark.asyncio
async def test_logout_never_sends_our_own_user_id_as_the_hint(client, db_session):
    # Entra has never seen this UUID. Passing it looks plausible and silently
    # produces the account picker, so it must never leak into the URL.
    user, _ = await _signed_in_client(client, db_session, logout_hint="opaque-hint-from-entra")

    with _discovery():
        response = client.post("/api/auth/logout", follow_redirects=False)

    assert str(user.id) not in response.headers["location"]
    assert user.email not in response.headers["location"]


def test_logout_without_a_session_still_completes(client):
    with _discovery():
        response = client.post("/api/auth/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith(END_SESSION)


@pytest.mark.asyncio
async def test_logout_survives_an_unreachable_discovery_document(client, db_session):
    # The local session is revoked before the provider URL is built. A provider
    # outage must not turn that into a 500 that tells the user sign-out failed
    # when it actually succeeded.
    user, raw_token = await _signed_in_client(client, db_session)

    with patch(
        "routes.auth_routes.oauth.entra.load_server_metadata",
        new=AsyncMock(side_effect=RuntimeError("metadata unreachable")),
    ):
        response = client.post("/api/auth/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"{FRONTEND_URL}/login"
    assert await authenticate_session(db_session, raw_token) is None


@pytest.mark.asyncio
async def test_callback_captures_the_login_hint_claim(client, db_session):
    user = User(id=uuid.uuid4(), email="hinted@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    fake_token = {"userinfo": {"oid": "oid-h", "email": "hinted@smu.edu.sg", "login_hint": "opaque-hint"}}
    with patch("routes.auth_routes.oauth.entra.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        client.get("/api/auth/callback", follow_redirects=False)

    await db_session.refresh(user)
    assert user.logout_hint == "opaque-hint"


@pytest.mark.asyncio
async def test_callback_without_the_login_hint_claim_keeps_any_stored_hint(client, db_session):
    # The claim is optional and can be absent from one login. A usable stored
    # hint beats overwriting it with NULL.
    user = User(
        id=uuid.uuid4(),
        email="kept@smu.edu.sg",
        entra_oid="oid-k",
        role=UserRoleEnum.instructor,
        logout_hint="previously-captured",
    )
    db_session.add(user)
    await db_session.commit()

    fake_token = {"userinfo": {"oid": "oid-k", "email": "kept@smu.edu.sg"}}
    with patch("routes.auth_routes.oauth.entra.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        client.get("/api/auth/callback", follow_redirects=False)

    await db_session.refresh(user)
    assert user.logout_hint == "previously-captured"


@pytest.mark.asyncio
async def test_a_new_login_leaves_other_sessions_alive(db_session, client):
    # Signing in on a second device must not sign the first one out. This is
    # why the callback does not revoke anything, and therefore why sessions
    # accumulate - see the note on GuestRoute in 08-auth-and-security.md.
    #
    # It is also not fixable at the callback: __Host-session is SameSite=strict
    # and /api/auth/callback is reached by a cross-site redirect from Microsoft,
    # so the browser withholds the existing cookie and the server has no way to
    # tell which prior session belonged to this browser.
    user = User(id=uuid.uuid4(), email="two@smu.edu.sg", entra_oid="oid-two", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    first_device = await create_session(db_session, user.id)

    fake_token = {"userinfo": {"oid": "oid-two", "email": "two@smu.edu.sg"}}
    with patch("routes.auth_routes.oauth.entra.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert await authenticate_session(db_session, first_device) is not None
    live = (await db_session.execute(select(UserSession).where(UserSession.deleted_at.is_(None)))).scalars().all()
    assert len(live) == 2
