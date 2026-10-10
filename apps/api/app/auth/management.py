import asyncio
import logging
import re
import secrets
import time

import httpx

from config import AUTH0_CLIENT_ID, AUTH0_DOMAIN, AUTH0_M2M_CLIENT_ID, AUTH0_M2M_CLIENT_SECRET
from exceptions import Auth0ProvisioningError

logger = logging.getLogger(__name__)

# Auth0's default name for a tenant's first Database connection. Not
# configurable elsewhere in this app - there is exactly one connection.
_DB_CONNECTION = "Username-Password-Authentication"

_client = httpx.AsyncClient(base_url=f"https://{AUTH0_DOMAIN}", timeout=httpx.Timeout(10.0))

# Cached Management API token and when to stop using it (monotonic seconds).
_token: tuple[str, float] | None = None

# Auth0 can still report an email as taken for a moment after its credential
# was deleted, so a create right after a delete gets a few spaced retries.
_CREATE_ATTEMPTS = 3
_CREATE_RETRY_DELAY_SECONDS = 1.0


# The invitee never sees this password, they reset it with the emailed link, but
# Auth0 still checks it against the connection's password policy. token_urlsafe
# alone sometimes has no special character or a run of 3 identical characters,
# which fails the stricter policies - that was the random "Password is too weak" 400.
def _placeholder_password() -> str:
    while True:
        password = secrets.token_urlsafe(32) + "aA1!"  # one of each character class
        if not re.search(r"(.)\1\1", password):
            return password


# Builds the error to raise, logging Auth0's own response body first - the
# routes return a fixed message, so this log line is the only place it shows.
def _provisioning_error(message: str, exc: httpx.HTTPError) -> Auth0ProvisioningError:
    if isinstance(exc, httpx.HTTPStatusError):
        detail = f"{exc.response.status_code} {exc.response.text[:500]}"
    else:
        detail = repr(exc)
    logger.warning("%s: %s", message, detail)
    return Auth0ProvisioningError(f"{message}: {detail}")


# Gets an access token to the Auth0 Management API for the M2M app, reused until
# a minute before it expires. Fetching one per call burns through the tenant's
# M2M token quota and rate limit, which is what made provisioning fail at random.
async def _management_token() -> str:
    global _token
    if _token is not None and _token[1] > time.monotonic():
        return _token[0]

    response = await _client.post(
        "/oauth/token",
        json={
            "client_id": AUTH0_M2M_CLIENT_ID,
            "client_secret": AUTH0_M2M_CLIENT_SECRET,
            "audience": f"https://{AUTH0_DOMAIN}/api/v2/",
            "grant_type": "client_credentials",
        },
    )
    response.raise_for_status()
    body = response.json()
    _token = (body["access_token"], time.monotonic() + body["expires_in"] - 60)
    return _token[0]


# Asks Auth0 to email the invitee the password-set link for their existing credential.
async def _send_invite_email(email: str) -> None:
    try:
        invite = await _client.post(
            "/dbconnections/change_password",
            json={
                "client_id": AUTH0_CLIENT_ID,
                "email": email,
                "connection": _DB_CONNECTION,
            },
        )
        invite.raise_for_status()
    except httpx.HTTPError as exc:
        raise _provisioning_error(f"Could not email an invite to {email}", exc) from exc


# Creates the Auth0-side credential for a newly provisioned user and has
# Auth0 email them a password-set link directly.
async def invite_user(email: str) -> str:
    try:
        headers = {"Authorization": f"Bearer {await _management_token()}"}

        for attempt in range(1, _CREATE_ATTEMPTS + 1):
            created = await _client.post(
                "/api/v2/users",
                headers=headers,
                json={
                    "email": email,
                    "connection": _DB_CONNECTION,
                    "password": _placeholder_password(),
                    # Set to False to prevent verification email from being sent
                    "email_verified": False,
                    "verify_email": False,
                    # Set flag so invitee receive the correct email instead of "Reset Password"
                    "app_metadata": {"pending_activation": True},
                },
            )
            # 409 straight after deleting this email's old credential is Auth0 catching up, not a real clash.
            if created.status_code != httpx.codes.CONFLICT or attempt == _CREATE_ATTEMPTS:
                break
            logger.info("Auth0 still reports %s as taken, retrying (attempt %d).", email, attempt)
            await asyncio.sleep(_CREATE_RETRY_DELAY_SECONDS)
        created.raise_for_status()
        auth0_user_id = created.json()["user_id"]
    except httpx.HTTPError as exc:
        raise _provisioning_error(f"Could not create an Auth0 credential for {email}", exc) from exc

    try:
        await _send_invite_email(email)
    except Auth0ProvisioningError:
        # The credential exists but the invitee can never learn that; don't leave it to 409 the retry.
        await delete_auth0_user(auth0_user_id)
        raise

    return auth0_user_id


# Re-sends the invite for a credential created earlier, without creating anything.
async def resend_invite_email(email: str) -> None:
    await _send_invite_email(email)


# Find user by Auth0 email in the Auth0 users database.
async def find_auth0_user_id_by_email(email: str) -> str | None:
    try:
        headers = {"Authorization": f"Bearer {await _management_token()}"}
        response = await _client.get("/api/v2/users-by-email", headers=headers, params={"email": email})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise _provisioning_error(f"Could not look up Auth0 user {email}", exc) from exc

    for match in response.json():
        if any(identity.get("connection") == _DB_CONNECTION for identity in match.get("identities", [])):
            return match["user_id"]
    return None


# Delete an Auth0 user from the Auth0 users database by their auth0_user_id. Used for rollback and soft-deleting users.
async def delete_auth0_user(auth0_user_id: str) -> bool:
    try:
        headers = {"Authorization": f"Bearer {await _management_token()}"}
        response = await _client.delete(f"/api/v2/users/{auth0_user_id}", headers=headers)
        response.raise_for_status()
    except httpx.HTTPError:
        logger.exception(
            "Could not delete Auth0 user %s - this email is now stuck against a live Auth0 "
            "credential and must be cleaned up manually (check the M2M app has delete:users).",
            auth0_user_id,
        )
        return False
    return True
