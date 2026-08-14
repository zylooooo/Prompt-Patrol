from authlib.integrations.starlette_client import OAuth

from config import ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET, ENTRA_CONFIGURED, ENTRA_TENANT_ID

oauth = OAuth()

if ENTRA_CONFIGURED:
    oauth.register(
        name="entra",
        client_id=ENTRA_CLIENT_ID,
        client_secret=ENTRA_CLIENT_SECRET,
        server_metadata_url=(
            f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}"
            "/v2.0/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
    )
