from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends, HTTPException, Request, status

from db import get_db
from models import User, UserRoleEnum

SESSION_COOKIE_NAME = "__Host-session"

ROLE_ORDER = {
    UserRoleEnum.teaching_assistant: 0,
    UserRoleEnum.instructor: 1,
    UserRoleEnum.root_admin: 2,
}


# Resolves the authenticated user from a valid session cookie.
async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    from services.sessions import authenticate_session
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = await authenticate_session(db, raw_token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalid or expired")
    return user


# Creates a FastAPI dependency that enforces a minimum user role.
def require_role(min_role: UserRoleEnum):
    # Rejects authenticated users whose role is below the required level.
    def dependency(user: User = Depends(get_current_user)) -> User:
        if ROLE_ORDER[user.role] < ROLE_ORDER[min_role]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency
