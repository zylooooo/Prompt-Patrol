import logging
from datetime import UTC, datetime

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth import SESSION_COOKIE_NAME, ActiveSession, get_current_session, oauth, require_role
from config import ENTRA_REDIRECT_URI, FRONTEND_URL
from db import get_db
from models import User, UserRoleEnum
from schemas import MeResponse, SessionResponse
from services import create_session, record_logout_hint, resolve_or_bind_user, sign_out_everywhere
from services.sessions import SESSION_IDLE_TTL
from services.users_service import LoginRejection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

ENTRA_USER_CANCELLED = "access_denied"


# Redirects the user to the frontend login page with an error code.
def _login_redirect(error_code: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"{FRONTEND_URL}/login?error={error_code}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# Builds the Entra sign-out URL, falling back to the frontend login page on failure.
async def _entra_logout_url(user: User | None) -> str:
    params = {"post_logout_redirect_uri": FRONTEND_URL}
    if user is not None and user.logout_hint:
        params["logout_hint"] = user.logout_hint

    try:
        result = await oauth.entra.create_logout_url(**params)
    except Exception:
        logger.exception("Could not build the Entra sign-out URL; the local session was still revoked.")
        return f"{FRONTEND_URL}/login"
    return result["url"]


# Starts the Entra authorization flow with an optional login hint.
@router.get("/login")
async def login(request: Request, login_hint: str | None = None):
    kwargs = {"login_hint": login_hint} if login_hint else {}
    return await oauth.entra.authorize_redirect(request, ENTRA_REDIRECT_URI, **kwargs)


# Completes Entra authentication and creates a local user session.
@router.get("/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        token = await oauth.entra.authorize_access_token(request)
    except OAuthError as exc:
        if exc.error == ENTRA_USER_CANCELLED:
            logger.info("Entra sign-in cancelled by the user.")
            return _login_redirect("sign_in_cancelled")
        logger.warning(
            "Entra callback rejected (error=%s, description=%s).",
            exc.error,
            exc.description,
        )
        return _login_redirect("sign_in_failed")
    claims = token["userinfo"]
    email = claims.get("email") or claims["preferred_username"]

    resolved = await resolve_or_bind_user(db, oid=claims["oid"], email=email)
    if isinstance(resolved, LoginRejection):
        # The codes match REDIRECT_ERROR_MESSAGES in pages/LoginPage.tsx.
        return _login_redirect(resolved.value)
    user = resolved
    await record_logout_hint(db, user, claims.get("login_hint"))

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


# Revokes every session this user holds, then redirects through Entra sign-out.
@router.post("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    user = await sign_out_everywhere(db, raw_token) if raw_token else None

    response = RedirectResponse(
        url=await _entra_logout_url(user),
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
