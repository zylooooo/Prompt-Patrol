import logging
from datetime import UTC, datetime
from urllib.parse import urlencode

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth import SESSION_COOKIE_NAME, ActiveSession, get_current_session, oauth, require_role
from config import AUTH0_CLIENT_ID, AUTH0_DOMAIN, AUTH0_REDIRECT_URI, FRONTEND_URL
from db import get_db
from models import User, UserRoleEnum
from schemas import MeResponse, SessionResponse
from services import (
    SESSION_IDLE_TTL,
    LoginRejection,
    create_session,
    resolve_user,
    sign_out_everywhere,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

AUTH0_USER_CANCELLED = "access_denied"


# Redirects the user to the frontend login page with an error code.
def _login_redirect(error_code: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"{FRONTEND_URL}/login?error={error_code}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# Builds the Auth0 sign-out URL, sent to the frontend for client-side redirect.
def _auth0_logout_url(return_to: str = FRONTEND_URL) -> str:
    params = urlencode({"client_id": AUTH0_CLIENT_ID, "returnTo": return_to})
    return f"https://{AUTH0_DOMAIN}/v2/logout?{params}"


# Starts the Auth0 authorization flow with an optional login hint.
@router.get("/login")
async def login(request: Request, login_hint: str | None = None, force_account_chooser: bool = False):
    kwargs = {"login_hint": login_hint} if login_hint else {}
    if force_account_chooser:
        # Set by the frontend right after our own logout to ensure consistent login experience
        # User's email will be saved when redirected to Auth0 login page.
        kwargs["prompt"] = "login"
    return await oauth.auth0.authorize_redirect(request, AUTH0_REDIRECT_URI, **kwargs)


# Completes Auth0 authentication and creates a local user session.
@router.get("/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        token = await oauth.auth0.authorize_access_token(request)
    except OAuthError as exc:
        if exc.error == AUTH0_USER_CANCELLED:
            logger.info("Auth0 sign-in cancelled by the user.")
            return _login_redirect("sign_in_cancelled")
        logger.warning(
            "Auth0 callback rejected (error=%s, description=%s).",
            exc.error,
            exc.description,
        )
        return _login_redirect("sign_in_failed")
    claims = token["userinfo"]
    email = claims.get("email") or claims["preferred_username"]

    resolved = await resolve_user(db, sub=claims["sub"], email=email)
    if isinstance(resolved, LoginRejection):
        # Check if user is deleted/deactivated, if they are redirect them to logout on client side.
        return_to = f"{FRONTEND_URL}/login?error={resolved.value}"
        return RedirectResponse(url=_auth0_logout_url(return_to), status_code=status.HTTP_303_SEE_OTHER)
    user = resolved

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


# Revokes every session this user holds, then redirects through Auth0 sign-out.
@router.post("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        await sign_out_everywhere(db, raw_token)

    response = RedirectResponse(
        url=_auth0_logout_url(),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return response


# Returns the authenticated user's identity and when their session expires.
@router.get("/me", response_model=MeResponse)
async def me(
    user: User = Depends(require_role(UserRoleEnum.teaching_assistant)),
    session: ActiveSession = Depends(get_current_session),
):
    return MeResponse(
        email=user.email,
        role=user.role,
        provisioned_by=user.provisioned_by,
        session=SessionResponse(
            expires_at=session.expires_at,
            idle_expires_at=session.idle_expires_at,
            absolute_expires_at=session.absolute_expires_at,
            expires_in_seconds=max(0, int((session.expires_at - datetime.now(UTC)).total_seconds())),
            capped=session.capped,
            idle_timeout_seconds=int(SESSION_IDLE_TTL.total_seconds()),
        ),
    )
