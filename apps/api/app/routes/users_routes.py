import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_role
from db import get_db
from exceptions import (
    EmailAlreadyExistsError,
    InvalidStatusTransitionError,
    InvalidSupervisorError,
    UserNotFoundError,
)
from models import User, UserRoleEnum, UserStatusEnum
from schemas import (
    StatusChangeRequest,
    SupervisorChangeRequest,
    UserCreateRequest,
    UserListResponse,
    UserResponse,
)
from services import (
    create_user,
    deactivate_user,
    delete_user,
    get_user_by_id,
    list_users,
    reactivate_user,
    set_supervisor,
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
    actor: User = Depends(require_role(UserRoleEnum.instructor)),
    db: AsyncSession = Depends(get_db),
):
    """
    Create new user endpoint. Authorization checks performed in service layer.
    """
    try:
        user = await create_user(
            db,
            actor,
            create_request.email,
            create_request.role,
            create_request.display_name,
            create_request.supervisor_id,
        )
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
    return user


@router.post("/{user_id}/supervisor", response_model=UserResponse)
async def set_supervisor_route(
    user_id: uuid.UUID,
    body: SupervisorChangeRequest,
    actor: User = Depends(require_role(UserRoleEnum.instructor)),
    db: AsyncSession = Depends(get_db),
):
    """
    Moves a teaching assistant to a different instructor, or unassigns them with
    a null supervisor. Assigning is a root admin act; an instructor may only
    release their own assistant. The rule lives in the service.

    Returns the row so the caller can see the resulting assignment without a
    follow-up read, matching the status transitions.
    """
    try:
        return await set_supervisor(db, actor, user_id, body.supervisor_id)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to change this user's supervisor.",
        )
    except UserNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    except InvalidSupervisorError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That supervisor is not an active instructor.",
        )
    except InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user_route(
    user_id: uuid.UUID,
    body: StatusChangeRequest | None = None,
    actor: User = Depends(require_role(UserRoleEnum.instructor)),
    db: AsyncSession = Depends(get_db),
):
    """Removes operational access, reversibly. Delegation enforced in the service."""
    return await _transition_route(deactivate_user, db, actor, user_id, body)


@router.post("/{user_id}/reactivate", response_model=UserResponse)
async def reactivate_user_route(
    user_id: uuid.UUID,
    body: StatusChangeRequest | None = None,
    actor: User = Depends(require_role(UserRoleEnum.instructor)),
    db: AsyncSession = Depends(get_db),
):
    """Returns a deactivated user to active. Cannot revive a deleted one."""
    return await _transition_route(reactivate_user, db, actor, user_id, body)


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
