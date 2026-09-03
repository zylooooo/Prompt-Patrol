import logging
import secrets

import httpx

from config import AUTH0_CLIENT_ID, AUTH0_DOMAIN, AUTH0_M2M_CLIENT_ID, AUTH0_M2M_CLIENT_SECRET
from exceptions import Auth0ProvisioningError

logger = logging.getLogger(__name__)

# Auth0's default name for a tenant's first Database connection. Not
# configurable elsewhere in this app - there is exactly one connection.
_DB_CONNECTION = "Username-Password-Authentication"

_client = httpx.AsyncClient(base_url=f"https://{AUTH0_DOMAIN}", timeout=httpx.Timeout(10.0))


# Helper function to get an access token to the Auth0 Mangement API for the M2M app.
async def _management_token() -> str:
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
    return response.json()["access_token"]


# Creates the Auth0-side credential for a newly provisioned user and has
# Auth0 email them a password-set link directly.
async def invite_user(email: str) -> str:
    try:
        headers = {"Authorization": f"Bearer {await _management_token()}"}

        created = await _client.post(
            "/api/v2/users",
            headers=headers,
            json={
                "email": email,
                "connection": _DB_CONNECTION,
                # Random password, invitee will reset with the emailed link.
                "password": secrets.token_urlsafe(32),
                # Set to False to prevent verification email from being sent
                "email_verified": False,
                "verify_email": False,
                # Set flag so invitee receive the correct email instead of "Reset Password"
                "app_metadata": {"pending_activation": True},
            },
        )
        created.raise_for_status()
        auth0_user_id = created.json()["user_id"]

        # Send the invite email with password reset link directly to the user.
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
        raise Auth0ProvisioningError(f"Could not create an Auth0 credential for {email}: {exc}") from exc

    return auth0_user_id


# Find user by Auth0 email in the Auth0 users database.
async def find_auth0_user_id_by_email(email: str) -> str | None:
    try:
        headers = {"Authorization": f"Bearer {await _management_token()}"}
        response = await _client.get("/api/v2/users-by-email", headers=headers, params={"email": email})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise Auth0ProvisioningError(f"Could not look up Auth0 user {email}: {exc}") from exc

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
