import uuid
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import pytest
from authlib.integrations.base_client.errors import OAuthError
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from sqlalchemy import select

from auth import SessionFailure
from config import AUTH0_CLIENT_ID, AUTH0_DOMAIN, FRONTEND_URL
from db import get_db
from main import app
from models import User, UserRoleEnum, UserSession, UserStatusEnum
from services import authenticate_session, create_session
from services.sessions import SESSION_IDLE_TTL


@pytest.fixture
def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_callback_creates_session_for_provisioned_user(client, db_session):
    user = User(id=uuid.uuid4(), email="prov@smu.edu.sg", auth0_sub="oid-prov", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    fake_token = {"userinfo": {"sub": "oid-prov", "email": "prov@smu.edu.sg"}}
    with patch("routes.auth_routes.oauth.auth0.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert "__Host-session" in response.cookies
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "samesite=strict" in cookie_header.lower()


@pytest.mark.asyncio
async def test_callback_signs_in_when_auth0_sends_a_different_email_case(client, db_session):
    # End to end version of the provisioning-case bug: the row is correct, the
    # person is real, and the only difference is capitalisation in the claim.
    # This used to land on /login?error=not_provisioned.
    user = User(id=uuid.uuid4(), email="ada@smu.edu.sg", auth0_sub="oid-ada", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    fake_token = {"userinfo": {"sub": "oid-ada", "email": "Ada@SMU.edu.sg"}}
    with patch("routes.auth_routes.oauth.auth0.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == FRONTEND_URL
    assert "__Host-session" in response.cookies


@pytest.mark.asyncio
async def test_callback_redirects_unprovisioned_user(client, db_session):
    # Auth0 already completed its own login before we ever see the rejection,
    # so the rejection must route through Auth0 logout - otherwise Auth0's SSO
    # cookie survives and the next /login silently re-authenticates the same
    # identity instead of letting the user pick a different one.
    fake_token = {"userinfo": {"sub": "oid-x", "email": "nobody@smu.edu.sg"}}
    with patch("routes.auth_routes.oauth.auth0.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(f"https://{AUTH0_DOMAIN}/v2/logout")
    assert f"client_id={AUTH0_CLIENT_ID}" in location
    assert quote(f"{FRONTEND_URL}/login?error=not_provisioned", safe="") in location
    assert "__Host-session" not in response.cookies
    result = await db_session.execute(select(UserSession))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_callback_issues_no_session_on_attempted_account_takeover(client, db_session):
    victim = User(
        id=uuid.uuid4(),
        email="victim@smu.edu.sg",
        auth0_sub="victim-oid",
        role=UserRoleEnum.root_admin,
    )
    db_session.add(victim)
    await db_session.commit()

    attacker = {"userinfo": {"sub": "attacker-oid", "email": "victim@smu.edu.sg"}}
    with patch("routes.auth_routes.oauth.auth0.authorize_access_token", new=AsyncMock(return_value=attacker)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(f"https://{AUTH0_DOMAIN}/v2/logout")
    assert quote(f"{FRONTEND_URL}/login?error=not_provisioned", safe="") in location
    assert "__Host-session" not in response.cookies
    assert (await db_session.execute(select(UserSession))).scalars().all() == []
    await db_session.refresh(victim)
    assert victim.auth0_sub == "victim-oid"


@pytest.mark.asyncio
async def test_callback_signs_out_of_auth0_for_a_deactivated_account(client, db_session):
    user = User(
        id=uuid.uuid4(),
        email="off@smu.edu.sg",
        auth0_sub="oid-off",
        role=UserRoleEnum.instructor,
        status=UserStatusEnum.deactivated,
    )
    db_session.add(user)
    await db_session.commit()

    fake_token = {"userinfo": {"sub": "oid-off", "email": "off@smu.edu.sg"}}
    with patch("routes.auth_routes.oauth.auth0.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(f"https://{AUTH0_DOMAIN}/v2/logout")
    assert quote(f"{FRONTEND_URL}/login?error=deactivated", safe="") in location
    assert "__Host-session" not in response.cookies


def test_login_is_silent_sso_by_default(client):
    # openapi.yaml /api/auth/logout ("Two-step logout"): silent SSO readmission
    # is documented as intentional, not a bug, outside the post-logout window -
    # a plain visit to /login must keep using it.
    with patch(
        "routes.auth_routes.oauth.auth0.authorize_redirect",
        new=AsyncMock(return_value=RedirectResponse("https://login.microsoftonline.com/authorize", 302)),
    ) as mock_redirect:
        client.get("/api/auth/login", follow_redirects=False)

    assert "prompt" not in mock_redirect.call_args.kwargs


def test_login_forwards_login_hint_when_not_forcing_the_chooser(client):
    with patch(
        "routes.auth_routes.oauth.auth0.authorize_redirect",
        new=AsyncMock(return_value=RedirectResponse("https://login.microsoftonline.com/authorize", 302)),
    ) as mock_redirect:
        client.get("/api/auth/login?login_hint=ada@smu.edu.sg", follow_redirects=False)

    assert mock_redirect.call_args.kwargs["login_hint"] == "ada@smu.edu.sg"
    assert "prompt" not in mock_redirect.call_args.kwargs


def test_login_forces_reauth_right_after_our_own_logout(client):
    # Regression: without prompt=login, a live Auth0 SSO cookie right after our
    # own logout makes Auth0 silently re-authenticate instead of showing an
    # interactive screen, so the user never appears to leave our login page.
    with patch(
        "routes.auth_routes.oauth.auth0.authorize_redirect",
        new=AsyncMock(return_value=RedirectResponse("https://example.auth0.com/authorize", 302)),
    ) as mock_redirect:
        client.get("/api/auth/login?force_account_chooser=1", follow_redirects=False)

    assert mock_redirect.call_args.kwargs["prompt"] == "login"


def test_login_forwards_login_hint_when_forcing_reauth(client):
    # Regression: forcing an interactive Auth0 login after our own logout must
    # not also throw away an email the frontend already has cached - Auth0's
    # /authorize accepts login_hint and prompt=login together.
    with patch(
        "routes.auth_routes.oauth.auth0.authorize_redirect",
        new=AsyncMock(return_value=RedirectResponse("https://example.auth0.com/authorize", 302)),
    ) as mock_redirect:
        client.get(
            "/api/auth/login?login_hint=ada@smu.edu.sg&force_account_chooser=1",
            follow_redirects=False,
        )

    assert mock_redirect.call_args.kwargs["prompt"] == "login"
    assert mock_redirect.call_args.kwargs["login_hint"] == "ada@smu.edu.sg"


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
    body = response.json()
    assert body["email"] == "loggedin@smu.edu.sg"
    assert body["role"] == "instructor"
    # The SPA counts down to expires_at to warn before eviction rather than
    # discover it on the next request, so /me must carry the deadlines.
    assert set(body["session"]) == {
        "expires_at",
        "idle_expires_at",
        "absolute_expires_at",
        "expires_in_seconds",
        "capped",
        "idle_timeout_seconds",
    }
    assert body["session"]["idle_timeout_seconds"] == int(SESSION_IDLE_TTL.total_seconds())
    assert body["session"]["capped"] is False
    # Counted from receipt, never subtracted from the browser clock.
    assert 0 < body["session"]["expires_in_seconds"] <= SESSION_IDLE_TTL.total_seconds()


def test_callback_sends_a_cancelled_sign_in_to_the_spa_login(client):
    # Regression: this used to redirect to /api/auth/login, which re-enters the
    # Auth0 redirect immediately - a user who cancelled was thrown back at the
    # prompt they had just dismissed and could never reach our own login page.
    error = OAuthError(error="access_denied", description="user cancelled")
    with patch("routes.auth_routes.oauth.auth0.authorize_access_token", new=AsyncMock(side_effect=error)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"{FRONTEND_URL}/login?error=sign_in_cancelled"
    assert "__Host-session" not in response.cookies


def test_callback_sends_any_other_oauth_failure_to_the_spa_login(client):
    error = OAuthError(error="mismatching_state", description="CSRF Warning!")
    with patch("routes.auth_routes.oauth.auth0.authorize_access_token", new=AsyncMock(side_effect=error)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"{FRONTEND_URL}/login?error=sign_in_failed"
    assert "__Host-session" not in response.cookies


def test_callback_never_redirects_back_into_the_auth0_flow(client):
    # The loop guard. No callback failure may point the browser at a URL that
    # restarts the OIDC redirect - the user must always land somewhere with a
    # way out.
    for error in (
        OAuthError(error="access_denied", description="user cancelled"),
        OAuthError(error="mismatching_state", description="CSRF Warning!"),
        OAuthError(description='Missing "state" parameter'),
    ):
        with patch("routes.auth_routes.oauth.auth0.authorize_access_token", new=AsyncMock(side_effect=error)):
            response = client.get("/api/auth/callback", follow_redirects=False)

        assert "/api/auth/login" not in response.headers["location"]
        assert response.headers["location"].startswith(f"{FRONTEND_URL}/login?error=")


def test_callback_does_not_reflect_auth0_error_text_into_the_url(client):
    # error_description is provider-controlled. It must never reach a URL the
    # browser lands on.
    error = OAuthError(error="invalid_client", description="<script>alert(1)</script>")
    with patch("routes.auth_routes.oauth.auth0.authorize_access_token", new=AsyncMock(side_effect=error)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    location = response.headers["location"]
    assert "script" not in location
    assert "invalid_client" not in location
    assert location == f"{FRONTEND_URL}/login?error=sign_in_failed"


@pytest.mark.asyncio
async def test_callback_ignores_stale_cookie(client, db_session):
    fake_token = {"userinfo": {"sub": "oid-stale", "email": "stale@smu.edu.sg"}}
    with patch("routes.auth_routes.oauth.auth0.authorize_access_token", new=AsyncMock(return_value=fake_token)):
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
    assert response.json()["email"] == "owner@smu.edu.sg"
    assert response.json()["role"] == "teaching_assistant"


def test_no_gateway_header_trust_remains_in_the_auth_dependency():
    # Guards the shape, not just the behaviour: authentication must not branch on
    # the environment, or the bypass returns the moment ENVIRONMENT changes.
    # Inspects the executable body only - the docstring deliberately names the
    # removed header so the next reader knows why it must not come back.
    import ast
    import inspect
    import textwrap

    from auth import dependencies

    # Both halves: get_current_session reads the cookie, get_current_user is
    # the thin wrapper over it. Checking only one would let the bypass return
    # in the other.
    for target in (dependencies.get_current_session, dependencies.get_current_user):
        function = ast.parse(textwrap.dedent(inspect.getsource(target))).body[0]
        body = function.body
        if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        code = "\n".join(ast.unparse(node) for node in body)

        assert "X-PP-User-Id" not in code
        assert "ENVIRONMENT" not in code


def test_auth0_routes_are_always_mounted():
    assert {"/api/auth/login", "/api/auth/callback"} <= set(app.openapi()["paths"])


def test_no_password_less_dev_login_exists(client):
    assert not [path for path in app.openapi()["paths"] if "/dev" in path]
    assert client.post("/api/auth/dev/login", json={"email": "a@b.c"}).status_code == 404
    assert client.get("/api/auth/dev/users").status_code == 404


# --- who the session belongs to ---------------------------------------------
# `provisioned_by` is the only supervision edge the system has, and the SPA gates
# a teaching assistant's screening screens on it. It has to ride on this payload:
# reading it from /api/users/me instead costs a second round trip on every page,
# and a TA cannot list users to get it another way.


@pytest.mark.asyncio
async def test_me_reports_who_provisioned_the_account(client, db_session):
    instructor = User(id=uuid.uuid4(), email="teach@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(instructor)
    await db_session.commit()
    assistant = User(
        id=uuid.uuid4(),
        email="ta@smu.edu.sg",
        role=UserRoleEnum.teaching_assistant,
        provisioned_by=instructor.id,
    )
    db_session.add(assistant)
    await db_session.commit()
    client.cookies.set("__Host-session", await create_session(db_session, assistant.id))

    body = client.get("/api/auth/me").json()

    assert body["provisioned_by"] == str(instructor.id)


@pytest.mark.asyncio
async def test_me_reports_a_null_provisioner_for_a_seeded_account(client, db_session):
    # Accounts seeded by scripts/provision_user carry no provisioner, so this is
    # null rather than absent - the SPA reads "no supervisor" from it.
    seeded = User(id=uuid.uuid4(), email="seeded@smu.edu.sg", role=UserRoleEnum.teaching_assistant)
    db_session.add(seeded)
    await db_session.commit()
    client.cookies.set("__Host-session", await create_session(db_session, seeded.id))

    body = client.get("/api/auth/me").json()

    assert body["provisioned_by"] is None


# --- sign-out ---------------------------------------------------------------
# Logout had no tests at all before 2026-08-16, despite being the route with the
# most side effects: it revokes a row, clears a cookie, and hands the browser to
# a third party.


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

    response = client.post("/api/auth/logout", follow_redirects=False)

    assert response.status_code == 303
    assert await authenticate_session(db_session, raw_token) is SessionFailure.session_revoked


@pytest.mark.asyncio
async def test_logout_ends_this_users_other_sessions_too(client, db_session):
    # Sign-out is global: nothing else in the product can reach a session on a
    # device you no longer hold, so ending only the calling browser would leave
    # someone who signed out on a shared machine with no remedy.
    user, raw_token = await _signed_in_client(client, db_session)
    other_device = await create_session(db_session, user.id)
    third_device = await create_session(db_session, user.id)

    response = client.post("/api/auth/logout", follow_redirects=False)

    assert response.status_code == 303
    for token in (raw_token, other_device, third_device):
        assert await authenticate_session(db_session, token) is SessionFailure.session_revoked


@pytest.mark.asyncio
async def test_logout_leaves_other_users_sessions_alone(client, db_session):
    _, raw_token = await _signed_in_client(client, db_session)
    bystander = User(id=uuid.uuid4(), email="stays@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(bystander)
    await db_session.commit()
    bystander_token = await create_session(db_session, bystander.id)

    client.post("/api/auth/logout", follow_redirects=False)

    assert await authenticate_session(db_session, raw_token) is SessionFailure.session_revoked
    assert not isinstance(await authenticate_session(db_session, bystander_token), SessionFailure)


@pytest.mark.asyncio
async def test_a_stale_token_cannot_sign_someone_out_again(client, db_session):
    # The token is resolved through a live session only. Otherwise a copied
    # cookie stays usable forever as a "sign this person out everywhere" button.
    user, raw_token = await _signed_in_client(client, db_session)
    client.post("/api/auth/logout", follow_redirects=False)

    fresh_login = await create_session(db_session, user.id)

    client.cookies.set("__Host-session", raw_token)
    replay = client.post("/api/auth/logout", follow_redirects=False)

    assert replay.status_code == 303
    assert not isinstance(await authenticate_session(db_session, fresh_login), SessionFailure)


@pytest.mark.asyncio
async def test_logout_clears_the_cookie_with_matching_attributes(client, db_session):
    # delete_cookie must repeat path/secure/httponly/samesite or the browser
    # keeps the original cookie and the user stays signed in locally.
    await _signed_in_client(client, db_session)

    response = client.post("/api/auth/logout", follow_redirects=False)

    header = response.headers["set-cookie"]
    assert "__Host-session=" in header
    assert "Path=/" in header
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "samesite=strict" in header.lower()


@pytest.mark.asyncio
async def test_logout_redirects_to_the_auth0_logout_endpoint(client, db_session):
    # Built directly from static config, unlike Entra's discovery-based
    # end_session_endpoint - no per-user hint, no network call at logout time.
    await _signed_in_client(client, db_session)

    response = client.post("/api/auth/logout", follow_redirects=False)

    location = response.headers["location"]
    assert location.startswith(f"https://{AUTH0_DOMAIN}/v2/logout")
    assert f"client_id={AUTH0_CLIENT_ID}" in location
    assert quote(FRONTEND_URL, safe="") in location.replace("%2F", "%2F")
    # No per-user hint - the Entra-specific logout_hint mechanism is gone.
    assert "logout_hint" not in location


def test_logout_without_a_session_still_completes(client):
    response = client.post("/api/auth/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"https://{AUTH0_DOMAIN}/v2/logout")


@pytest.mark.asyncio
async def test_a_new_login_leaves_other_sessions_alive(db_session, client):
    # Signing in on a second device must not sign the first one out. This is
    # why the callback does not revoke anything, and therefore why sessions
    # accumulate - see the note on GuestRoute in 08-auth-and-security.md.
    #
    # It is also not fixable at the callback: __Host-session is SameSite=strict
    # and /api/auth/callback is reached by a cross-site redirect from Auth0,
    # so the browser withholds the existing cookie and the server has no way to
    # tell which prior session belonged to this browser.
    user = User(id=uuid.uuid4(), email="two@smu.edu.sg", auth0_sub="oid-two", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    first_device = await create_session(db_session, user.id)

    fake_token = {"userinfo": {"sub": "oid-two", "email": "two@smu.edu.sg"}}
    with patch("routes.auth_routes.oauth.auth0.authorize_access_token", new=AsyncMock(return_value=fake_token)):
        response = client.get("/api/auth/callback", follow_redirects=False)

    assert response.status_code == 303
    assert not isinstance(await authenticate_session(db_session, first_device), SessionFailure)
    live = (await db_session.execute(select(UserSession).where(UserSession.deleted_at.is_(None)))).scalars().all()
    assert len(live) == 2


# --- why a 401 happened ----------------------------------------------------


def test_a_401_with_no_cookie_says_so(client):
    # "not_signed_in" is what the login page reads as "say nothing" - a first
    # visitor has not been signed out of anything and must not be told they were.
    body = client.get("/api/auth/me").json()

    assert body["detail"]["code"] == SessionFailure.not_signed_in.value


def test_a_401_on_an_unrecognised_cookie_says_so(client):
    client.cookies.set("__Host-session", "not-a-real-token")

    body = client.get("/api/auth/me").json()

    assert body["detail"]["code"] == SessionFailure.session_unknown.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"deleted_at": "now"}, SessionFailure.session_revoked),
        ({"last_active_at": "long ago"}, SessionFailure.session_expired),
        ({"absolute_expires_at": "past"}, SessionFailure.session_ended),
    ],
    ids=["revoked", "idle", "capped"],
)
async def test_a_401_names_which_limit_ended_the_session(client, db_session, overrides, expected):
    # The whole point of the change: every one of these used to return the same
    # opaque 401, so the SPA could only ever say "your session timed out" - and
    # for two of the three that sentence is false.
    from datetime import UTC, datetime, timedelta

    from services.sessions import SESSION_ABSOLUTE_TTL, SESSION_IDLE_TTL

    user = User(id=uuid.uuid4(), email=f"why-{expected.value}@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)

    now = datetime.now(UTC)
    values = {
        "now": now,
        "long ago": now - SESSION_IDLE_TTL - timedelta(minutes=1),
        "past": now - timedelta(seconds=1),
    }
    row = (await db_session.execute(select(UserSession))).scalars().one()
    for field, key in overrides.items():
        setattr(row, field, values[key])
    if "absolute_expires_at" not in overrides:
        row.absolute_expires_at = now + SESSION_ABSOLUTE_TTL
    await db_session.commit()

    client.cookies.set("__Host-session", raw_token)
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == expected.value


@pytest.mark.asyncio
async def test_a_401_after_deactivation_blames_the_account_not_the_session(client, db_session):
    # Being told the session expired sends this person to sign in again, which
    # cannot work. They need to be told to talk to an administrator.
    from models import UserStatusEnum

    user = User(id=uuid.uuid4(), email="turnedoff@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)

    user.status = UserStatusEnum.deactivated
    await db_session.commit()

    client.cookies.set("__Host-session", raw_token)
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == SessionFailure.account_deactivated.value


@pytest.mark.asyncio
async def test_a_probe_reads_the_session_without_reviving_it(client, db_session):
    # Observed live before the fix: the SPA's countdown reached zero, asked
    # /api/auth/me whether the session had expired, and the asking slid
    # last_active_at from 179s old back to 3s. An abandoned tab renewed itself
    # forever and the idle timeout did not exist.
    from datetime import UTC, datetime, timedelta

    user = User(id=uuid.uuid4(), email="probe@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)

    row = (await db_session.execute(select(UserSession))).scalars().one()
    row.last_active_at = datetime.now(UTC) - SESSION_IDLE_TTL + timedelta(minutes=1)
    await db_session.commit()
    aged = row.last_active_at

    client.cookies.set("__Host-session", raw_token)
    assert client.get("/api/auth/me?probe=1").status_code == 200

    await db_session.refresh(row)
    # SQLite drops the offset on the way back out, so both sides are compared naive.
    assert row.last_active_at.replace(tzinfo=None) == aged.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_an_ordinary_request_still_keeps_a_working_user_signed_in(client, db_session):
    # The other half: without the touch there is no sliding window at all, and
    # the bug this whole change exists to fix comes straight back.
    from datetime import UTC, datetime, timedelta

    user = User(id=uuid.uuid4(), email="touch@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)

    row = (await db_session.execute(select(UserSession))).scalars().one()
    row.last_active_at = datetime.now(UTC) - SESSION_IDLE_TTL + timedelta(minutes=1)
    await db_session.commit()
    aged = row.last_active_at

    client.cookies.set("__Host-session", raw_token)
    assert client.get("/api/auth/me").status_code == 200

    await db_session.refresh(row)
    assert row.last_active_at.replace(tzinfo=None) > aged.replace(tzinfo=None)
