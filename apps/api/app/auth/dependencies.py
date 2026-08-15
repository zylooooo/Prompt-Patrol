import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import ENVIRONMENT
from db import get_db
from models import User, UserRoleEnum

SESSION_COOKIE_NAME = "__Host-session"
GATEWAY_USER_ID_HEADER = "X-PP-User-Id"

# Rank the roles so require_role can just compare numbers instead of
# maintaining an allow-list per endpoint.
ROLE_ORDER = {
    UserRoleEnum.teaching_assistant: 0,
    UserRoleEnum.instructor: 1,
    UserRoleEnum.root_admin: 2,
}


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """
    Environment aware authentication dependency. In staging/prod it trusts
    the gateway's authentication header completely because of authorizer lambda
    and SG rules. In dev, it validates the session cookie directly and returns
    the user object.
    """
    from services.sessions import authenticate_session
    from services.users_service import get_user_by_id

    if ENVIRONMENT != "dev":
        raw_id = request.headers.get(GATEWAY_USER_ID_HEADER)
        if raw_id is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        actor_id = uuid.UUID(raw_id)
        # Self-lookup: id-equality check in _can_view_user passes regardless
        # of role, so a bare id stand-in is enough here.
        user = await get_user_by_id(db, User(id=actor_id), actor_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return user

    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = await authenticate_session(db, raw_token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalid or expired")
    return user


def require_role(min_role: UserRoleEnum):
    """
    FastAPI dependency factory: require_role(UserRoleEnum.instructor)
    yields a dependency that 401s if there's no valid session, 403s if the
    user's role ranks below min_role, else returns the user.
    """

    def dependency(user: User = Depends(get_current_user)) -> User:
        if ROLE_ORDER[user.role] < ROLE_ORDER[min_role]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency
