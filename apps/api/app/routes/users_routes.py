import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_role
from db import get_db
from exceptions import (
    Auth0ProvisioningError,
    EmailAlreadyExistsError,
    InvalidStatusTransitionError,
    InvalidSupervisorError,
    UserNotFoundError,
)
from models import User, UserRoleEnum, UserStatusEnum
from schemas import (
    StatusChangeRequest,
    SupervisorLinkRequest,
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserRolePatchRequest,
)
from services import (
    change_user_role,
    create_user,
    deactivate_user,
    delete_user,
    end_supervision,
    get_user_by_id,
    link_supervisor,
    list_users,
    reactivate_user,
    resend_invite,
)

# Dependency that requires the minimum role, forcing a valid session on every route.
router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(require_role(UserRoleEnum.teaching_assistant))],
)


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    actor: User = Depends(require_role(UserRoleEnum.teaching_assistant)),
):
    """Return current user profile"""
    return actor


@router.get("/", response_model=UserListResponse)
async def list_all_users(
    role: UserRoleEnum | None = None,
    status_filter: Annotated[list[UserStatusEnum] | None, Query(alias="status")] = None,
    # Bounded, per the contract. It was unbounded, so one request could ask the
    # database for the entire table; callers page with `cursor` instead.
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
    actor: User = Depends(require_role(UserRoleEnum.instructor)),
    db: AsyncSession = Depends(get_db),
):
    """
    Delegation-scoped directory listing. Authorization/scoping performed in
    service layer.

    Defaults to active users only. Pass `?status=deactivated&status=deleted` to
    widen it - deleted users are never returned unless asked for by name, so an
    ordinary administrative screen cannot show them by accident.
    """
    try:
        items, next_cursor = await list_users(
            db, actor, role, frozenset(status_filter) if status_filter else None, limit, cursor
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to list users with that role.",
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor")
    return UserListResponse(items=[UserResponse.model_validate(u) for u in items], next_cursor=next_cursor)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    actor: User = Depends(require_role(UserRoleEnum.teaching_assistant)),
    db: AsyncSession = Depends(get_db),
):
    """
    No role gate, teaching_assistant is the lowest role so this just
    requires a valid session. Role-based authorization determines if users
    can be read. Both "doesn't exist" and "exists but not visible to this actor"
    return 404, to prevent enumeration attacks.
    """
    target = await get_user_by_id(db, actor, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return target


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def provision_user(
    create_request: UserCreateRequest,
    actor: User = Depends(require_role(UserRoleEnum.root_admin)),
    db: AsyncSession = Depends(get_db),
):
    """
    root_admin provisioning. Instructors add teaching assistants through
    POST /api/users/teaching-assistants instead.

    An optional supervisor is linked in the same commit as the account, so
    the account, the link and the Auth0 invite land together or not at all.
    """
    try:
        user = await create_user(db, actor, create_request.email, create_request.role, create_request.supervisor_id)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to create a user with this role.",
        )
    except InvalidSupervisorError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That supervisor is not an active instructor.",
        )
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )
    except Auth0ProvisioningError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not create an Auth0 credential for this user. Nothing was saved - try again.",
        )
    return user


@router.patch("/{user_id}/role", response_model=UserResponse)
async def change_user_role_route(
    user_id: uuid.UUID,
    body: UserRolePatchRequest,
    actor: User = Depends(require_role(UserRoleEnum.root_admin)),
    db: AsyncSession = Depends(get_db),
):
    """
    Root-admin-only, isolated from provisioning (`POST /api/users`) so a role
    change is always its own distinct, audited action.
    """
    try:
        return await change_user_role(db, actor, user_id, body.role)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="root_admin accounts cannot have their role changed.",
        )
    except UserNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router.post("/{user_id}/supervisors", response_model=UserResponse)
async def add_supervisor_route(
    user_id: uuid.UUID,
    body: SupervisorLinkRequest,
    actor: User = Depends(require_role(UserRoleEnum.root_admin)),
    db: AsyncSession = Depends(get_db),
):
    """
    Places a teaching assistant on an instructor's team. Additive: other
    supervisors are kept, and linking an existing pair is a no-op.
    """
    try:
        return await link_supervisor(db, actor, user_id, body.instructor_id)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to place teaching assistants.",
        )
    except UserNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    except InvalidSupervisorError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only an active instructor can supervise, and only a teaching assistant can be supervised.",
        )
    except InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.delete("/{user_id}/supervisors/{instructor_id}", response_model=UserResponse)
async def remove_supervisor_route(
    user_id: uuid.UUID,
    instructor_id: uuid.UUID,
    actor: User = Depends(require_role(UserRoleEnum.instructor)),
    db: AsyncSession = Depends(get_db),
):
    """
    Ends one supervision ("Remove from team"). An instructor may end only their
    own link; anything else is 404, the same as a link that does not exist.
    """
    try:
        return await end_supervision(db, actor, user_id, instructor_id)
    except UserNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.post("/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user_route(
    user_id: uuid.UUID,
    body: StatusChangeRequest | None = None,
    actor: User = Depends(require_role(UserRoleEnum.root_admin)),
    db: AsyncSession = Depends(get_db),
):
    """Removes operational access, reversibly. root_admin only."""
    return await _transition_route(deactivate_user, db, actor, user_id, body)


@router.post("/{user_id}/reactivate", response_model=UserResponse)
async def reactivate_user_route(
    user_id: uuid.UUID,
    body: StatusChangeRequest | None = None,
    actor: User = Depends(require_role(UserRoleEnum.root_admin)),
    db: AsyncSession = Depends(get_db),
):
    """Returns a deactivated user to active. Cannot reactivate a deleted one."""
    return await _transition_route(reactivate_user, db, actor, user_id, body)


@router.post("/{user_id}/resend-invite", response_model=UserResponse)
async def resend_invite_route(
    user_id: uuid.UUID,
    actor: User = Depends(require_role(UserRoleEnum.instructor)),
    db: AsyncSession = Depends(get_db),
):
    """Re-sends the password-set email to an invitee who has never signed in."""
    try:
        return await resend_invite(db, actor, user_id)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to re-invite this user.",
        )
    except UserNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    except InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Auth0ProvisioningError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send the invite email. Try again.",
        )


@router.delete("/{user_id}", response_model=UserResponse)
async def delete_user_route(
    user_id: uuid.UUID,
    body: StatusChangeRequest | None = None,
    actor: User = Depends(require_role(UserRoleEnum.root_admin)),
    db: AsyncSession = Depends(get_db),
):
    """
    Logically removes a user. Terminal - there is no restore endpoint, by design.

    Returns the row rather than 204 so the caller can see the resulting status
    without a follow-up read, and so "it worked" and "it silently did nothing"
    are distinguishable.
    """
    return await _transition_route(delete_user, db, actor, user_id, body)


async def _transition_route(operation, db, actor, user_id, body):
    """One error-mapping path for all three transitions, so a new one cannot
    accidentally return a different status code for the same failure."""
    try:
        return await operation(db, actor, user_id, body.reason if body else None)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to change this user's status.",
        )
    except UserNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    except InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
