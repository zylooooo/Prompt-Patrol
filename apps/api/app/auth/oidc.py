from authlib.integrations.starlette_client import OAuth

from config import ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET, ENTRA_TENANT_ID

# Registers the "entra" OAuth client that routes/auth.py calls as oauth.entra
oauth = OAuth()
oauth.register(
    name="entra",
    client_id=ENTRA_CLIENT_ID,
    client_secret=ENTRA_CLIENT_SECRET,
    # Single-tenant scoped, only invited users can access or any users with SMU account
    server_metadata_url=(
        f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0/.well-known/openid-configuration"
    ),
    # PKCE code challenge using SHA256
    client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
)
