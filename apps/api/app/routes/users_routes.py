import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import require_role
from db import get_db
from models import User, UserRoleEnum
from schemas import UserResponse
from services import get_user_by_id

# Dependency that requires the minimum role, forcing a valid session on every route.
router = APIRouter(
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(require_role(UserRoleEnum.teaching_assistant))],
)


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
