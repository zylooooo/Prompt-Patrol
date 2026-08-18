from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User, UserRoleEnum

from .session_state import ActiveSession, SessionFailure

SESSION_COOKIE_NAME = "__Host-session"

ROLE_ORDER = {
    UserRoleEnum.teaching_assistant: 0,
    UserRoleEnum.instructor: 1,
    UserRoleEnum.root_admin: 2,
}


# Builds the 401 a browser can act on rather than just report.
def _unauthenticated(failure: SessionFailure) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": failure.value, "message": _FAILURE_SUMMARY[failure]},
    )


_FAILURE_SUMMARY = {
    SessionFailure.not_signed_in: "No session cookie was sent.",
    SessionFailure.session_unknown: "The session cookie matches no session.",
    SessionFailure.session_revoked: "This session was signed out.",
    SessionFailure.session_expired: "This session passed its inactivity limit.",
    SessionFailure.session_ended: "This session reached its maximum lifetime.",
    SessionFailure.account_deactivated: "This account is no longer active.",
}


# Resolves the caller's session, or raises a 401 that says which way it failed.
async def get_current_session(
    request: Request,
    probe: Annotated[bool, Query(include_in_schema=False)] = False,
    db: AsyncSession = Depends(get_db),
) -> ActiveSession:
    from services.sessions import authenticate_session

    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token is None:
        raise _unauthenticated(SessionFailure.not_signed_in)
    outcome = await authenticate_session(db, raw_token, touch=not probe)
    if isinstance(outcome, SessionFailure):
        raise _unauthenticated(outcome)
    return outcome


# Resolves the authenticated user from a valid session cookie.
async def get_current_user(session: ActiveSession = Depends(get_current_session)) -> User:
    return session.user


# Rejects a teaching assistant nobody supervises.
#
# `provisioned_by` is the only supervision edge the schema has, so an assistant
# with none belongs to no course and has nothing to screen for. The SPA refuses
# them too, but that is a courtesy to the user, not a control: it reads the
# session payload it is holding and can be skipped entirely. This is the check
# that counts.
#
# Only assistants are gated. An instructor or admin carries no supervisor by
# design, and the same rule shaped as "must have a supervisor" would lock out
# everyone above.
def require_screening_access(user: User = Depends(get_current_user)) -> User:
    if user.role == UserRoleEnum.teaching_assistant and user.provisioned_by is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not assigned to an instructor yet, so there is nothing to screen.",
        )
    return user


# Creates a FastAPI dependency that enforces a minimum user role.
def require_role(min_role: UserRoleEnum):
    # Rejects authenticated users whose role is below the required level.
    def dependency(user: User = Depends(get_current_user)) -> User:
        if ROLE_ORDER[user.role] < ROLE_ORDER[min_role]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency
