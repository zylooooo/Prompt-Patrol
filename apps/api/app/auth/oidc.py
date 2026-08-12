# Registers the "entra" OAuth client that routes/auth.py calls as oauth.entra
# (authorize_redirect / authorize_access_token).
from authlib.integrations.starlette_client import OAuth

from config import ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET, ENTRA_TENANT_ID

oauth = OAuth()
oauth.register(
    name="entra",
    client_id=ENTRA_CLIENT_ID,
    client_secret=ENTRA_CLIENT_SECRET,
    # Tenant-scoped, not /common - we don't want arbitrary Microsoft accounts
    # showing up in the login flow.
    server_metadata_url=(
        f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0/.well-known/openid-configuration"
    ),
    # code_challenge_method turns on PKCE alongside the confidential client
    # secret. Authlib handles generating/stashing the verifier and replaying
    # it at the callback, we don't touch it directly.
    client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
)
