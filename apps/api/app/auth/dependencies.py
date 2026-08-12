from fastapi import HTTPException, Request, status

from models import UserRoleEnum

# Rank the roles so require_role can just compare numbers instead of
# maintaining an allow-list per endpoint.
ROLE_ORDER = {
    UserRoleEnum.teaching_assistant: 0,
    UserRoleEnum.instructor: 1,
    UserRoleEnum.root_admin: 2,
}


def require_role(min_role: UserRoleEnum):
    """FastAPI dependency factory: require_role(UserRoleEnum.instructor)
    yields a dependency that 401s if SessionAuthMiddleware found no user,
    403s if their role ranks below min_role, else returns the user."""

    def dependency(request: Request):
        user = request.state.user
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        if ROLE_ORDER[user.role] < ROLE_ORDER[min_role]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency
