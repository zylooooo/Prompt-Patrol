import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import require_role
from db import get_db
from exceptions import EmailAlreadyExistsError, UserNotDeletedError
from models import User, UserRoleEnum
from schemas import UserResponse, UserCreateRequest, UserListResponse
from services import get_user_by_id, create_user, soft_delete_user, activate_user_by_id, list_users


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
    include_deleted: bool = False,
    limit: int = 50,
    cursor: str | None = None,
    actor: User = Depends(require_role(UserRoleEnum.instructor)),
    db: AsyncSession = Depends(get_db),
):
    """
    Delegation-scoped directory listing. Authorization/scoping performed in
    service layer.
    """
    try:
        items, next_cursor = await list_users(db, actor, role, include_deleted, limit, cursor)
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
        user = await create_user(db, actor, create_request.email, create_request.role)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to create a user with this role.",
        )
    except EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )
    return user

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    actor: User = Depends(require_role(UserRoleEnum.instructor)),
    db: AsyncSession = Depends(get_db)
):
    """
    Soft delete a user. Authorization checks performed in service layer.
    """
    try:
        await soft_delete_user(db, actor, user_id)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to delete this user.",
        )

@router.post("/{user_id}/restore", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def restore_user(
    user_id: uuid.UUID,
    actor: User = Depends(require_role(UserRoleEnum.instructor)),
    db: AsyncSession = Depends(get_db)
):
    """
    Restore a soft-deleted user. Authorization checks performed in service layer.
    """
    try:
        user = await activate_user_by_id(db, actor, user_id)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to restore this user.",
        )
    except UserNotDeletedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is not currently deleted.",
        )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
