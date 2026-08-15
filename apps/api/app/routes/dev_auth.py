import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import SESSION_COOKIE_NAME
from config import DEV_AUTH_ENABLED, ENTRA_CONFIGURED
from db import get_db
from models import User
from services.sessions import create_session

logger = logging.getLogger(__name__)

MAX_LISTED_USERS = 50


def _require_dev_auth() -> None:
    if not DEV_AUTH_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


router = APIRouter(
    prefix="/api/auth/dev",
    tags=["auth", "dev"],
    dependencies=[Depends(_require_dev_auth)],
)


class DevLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class DevUser(BaseModel):
    email: str
    role: str


class DevAuthInfo(BaseModel):
    entra_configured: bool
    users: list[DevUser]


@router.get("/users", response_model=DevAuthInfo)
async def list_provisioned_users(db: AsyncSession = Depends(get_db)) -> DevAuthInfo:
    result = await db.execute(
        select(User).where(User.deleted_at.is_(None)).order_by(User.email).limit(MAX_LISTED_USERS)
    )
    return DevAuthInfo(
        entra_configured=ENTRA_CONFIGURED,
        users=[DevUser(email=user.email, role=user.role.value) for user in result.scalars()],
    )


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def dev_login(payload: DevLoginRequest, db: AsyncSession = Depends(get_db)) -> Response:
    email = payload.email.strip()
    result = await db.execute(select(User).where(User.email == email, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account not provisioned")

    raw_token = await create_session(db, user.id)
    logger.warning(
        "Dev login issued a session for %s (%s) with no identity verification.",
        user.email,
        user.role.value,
    )

    response = Response(status_code=status.HTTP_204_NO_CONTENT)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response
