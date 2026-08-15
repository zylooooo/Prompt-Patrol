from authlib.integrations.starlette_client import OAuth

from config import ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET, ENTRA_CONFIGURED, ENTRA_TENANT_ID

# Registers the "entra" OAuth client that routes/auth_routes.py calls as
# oauth.entra. Registration is skipped entirely when no app registration is
# configured so the API still boots for local dev-login work.
oauth = OAuth()

if ENTRA_CONFIGURED:
    oauth.register(
        name="entra",
        client_id=ENTRA_CLIENT_ID,
        client_secret=ENTRA_CLIENT_SECRET,
        # Single-tenant scoped, not /common - we don't want arbitrary Microsoft
        # accounts showing up in the login flow.
        server_metadata_url=(
            f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}"
            "/v2.0/.well-known/openid-configuration"
        ),
        # code_challenge_method turns on PKCE (SHA256) alongside the confidential
        # client secret. Authlib handles generating/stashing the verifier and
        # replaying it at the callback, we don't touch it directly.
        client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
    )
