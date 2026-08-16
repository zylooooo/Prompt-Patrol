import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from models import UserRoleEnum, UserStatusEnum


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: UserRoleEnum
    status: UserStatusEnum
    provisioned_by: uuid.UUID | None
    created_at: datetime


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    email: str
    role: UserRoleEnum


class StatusChangeRequest(BaseModel):
    """Optional free-text note stored on the audit event, never shown to the
    user whose access changed."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class UserListResponse(BaseModel):
    items: list[UserResponse]
    next_cursor: str | None = None
