import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from models import UserRoleEnum, UserStatusEnum


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    role: UserRoleEnum
    status: UserStatusEnum
    provisioned_by: uuid.UUID | None
    created_at: datetime


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    email: str
    role: UserRoleEnum
    display_name: str | None = Field(default=None, max_length=200)
    """Optional placeholder shown before first login; Entra's `name` claim
    overwrites it thereafter, so it is never authoritative."""
    supervisor_id: uuid.UUID | None = None
    """The instructor who will supervise a new teaching assistant. Only a root
    admin may name one; an instructor supervises whoever they create."""


class SupervisorChangeRequest(BaseModel):
    """Moves a teaching assistant to a different instructor. Null unassigns them,
    which ends their screening access and signs them out."""

    model_config = ConfigDict(extra="forbid")

    supervisor_id: uuid.UUID | None = None


class StatusChangeRequest(BaseModel):
    """Optional free-text note stored on the audit event, never shown to the
    user whose access changed."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class UserListResponse(BaseModel):
    items: list[UserResponse]
    next_cursor: str | None = None
