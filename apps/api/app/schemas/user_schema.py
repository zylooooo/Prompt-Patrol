import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from models import UserRoleEnum


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: UserRoleEnum
    provisioned_by: uuid.UUID | None
    created_at: datetime
    deleted_at: datetime | None


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    email: str
    role: UserRoleEnum


class UserListResponse(BaseModel):
    items: list[UserResponse]
    next_cursor: str | None = None
