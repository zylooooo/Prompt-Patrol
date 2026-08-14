from urllib.parse import quote

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import require_role
from auth.middleware import SESSION_COOKIE_NAME
from auth.oidc import oauth
from config import ENTRA_CONFIGURED, ENTRA_REDIRECT_URI, ENTRA_TENANT_ID, FRONTEND_URL
from db import get_db
from models import UserRoleEnum, User
from services.sessions import create_session, revoke_session
from services.users import resolve_or_bind_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

entra_router = APIRouter()


@entra_router.get("/login")
async def login(request: Request, login_hint: str | None = None):
    kwargs = {"login_hint": login_hint} if login_hint else {}
    return await oauth.entra.authorize_redirect(request, ENTRA_REDIRECT_URI, **kwargs)


@entra_router.get("/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        token = await oauth.entra.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse(url="/api/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    claims = token["userinfo"]
    email = claims.get("email") or claims["preferred_username"]

    user = await resolve_or_bind_user(db, oid=claims["oid"], email=email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account not provisioned")

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
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        await revoke_session(db, raw_token)

    if ENTRA_CONFIGURED:
        logout_url = (
            f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/oauth2/v2.0/logout"
            f"?post_logout_redirect_uri={quote(FRONTEND_URL, safe='')}"
        )
    else:
        logout_url = FRONTEND_URL
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
    return {"email": user.email, "role": user.role}

if ENTRA_CONFIGURED:
    router.include_router(entra_router)
