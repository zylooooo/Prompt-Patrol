from urllib.parse import quote

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import require_role
from auth.middleware import SESSION_COOKIE_NAME
from auth.oidc import oauth
from config import ENTRA_REDIRECT_URI, ENTRA_TENANT_ID, FRONTEND_URL
from db import get_db
from models import UserRoleEnum, User
from services.sessions import create_session, revoke_session
from services.users import resolve_or_bind_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request, login_hint: str | None = None):
    """Redirects to Microsoft's authorize endpoint. Authlib stashes the PKCE
    code_verifier and OAuth state in the ppauthflow session cookie so
    /callback can validate the response later. login_hint just pre-fills the
    Microsoft sign-in form, it's not something we trust for identity."""
    kwargs = {"login_hint": login_hint} if login_hint else {}
    return await oauth.entra.authorize_redirect(request, ENTRA_REDIRECT_URI, **kwargs)


@router.get("/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Validates state and PKCE verifier against ppauthflow, redeems the code
    at Entra's token endpoint, and validates the returned ID token. Only the
    claims from that validated token get used below, the token itself is
    discarded and never stored."""
    try:
        token = await oauth.entra.authorize_access_token(request)
    except OAuthError:
        # Stale or replayed callback, e.g. an old tab, the back button, or
        # ppauthflow just expired. Send them back to try again.
        return RedirectResponse(url="/api/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    claims = token["userinfo"]
    email = claims.get("email") or claims["preferred_username"]

    # Role comes from our own users table, never from Entra claims/groups.
    user = await resolve_or_bind_user(db, oid=claims["oid"], email=email)
    if user is None:
        # They authenticated fine with Entra, they're just not allowlisted in
        # our users table. Send them back to the SPA with an error the login
        # page can show, rather than a bare JSON 403 on Entra's redirect.
        return RedirectResponse(
            url=f"{FRONTEND_URL}/login?error=not_provisioned",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    raw_token = await create_session(db, user.id)
    response = RedirectResponse(url=FRONTEND_URL, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


@router.post("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    """Revokes our own session first no matter what Entra does next, then
    ends the Microsoft browser session too. Skipping that second part means
    a re-visit to /api/auth/login would just silently sign the user back in
    without ever showing a prompt."""
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        await revoke_session(db, raw_token)

    logout_url = (
        f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri={quote(FRONTEND_URL, safe='')}"
    )
    response = RedirectResponse(url=logout_url, status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return response


@router.get("/me")
async def me(user: User = Depends(require_role(UserRoleEnum.teaching_assistant))):
    """min_role here is the lowest role we have, so this really just checks
    whether anyone valid is logged in. The frontend calls this on load to
    bootstrap its auth state."""
    return {"email": user.email, "role": user.role}
