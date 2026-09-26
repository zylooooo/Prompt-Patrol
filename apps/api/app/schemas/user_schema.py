import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models import UserRoleEnum, UserStatusEnum

# C0/C1 controls except tab and newline, plus angle brackets.
_UNSAFE_REASON_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f<>]")


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    role: UserRoleEnum
    status: UserStatusEnum
    provisioned_by: uuid.UUID | None
    # Active supervisors; [] for anyone who is not a TA.
    supervisor_ids: list[uuid.UUID]
    first_login_at: datetime | None
    created_at: datetime


class UserCreateRequest(BaseModel):
    """root_admin provisioning. No display name - the person chooses it after
    first sign-in 
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    email: str
    role: UserRoleEnum
    supervisor_id: uuid.UUID | None = None


class SupervisorLinkRequest(BaseModel):
    """root_admin places a teaching assistant under an active instructor"""

    model_config = ConfigDict(extra="forbid")

    instructor_id: uuid.UUID


class UserRolePatchRequest(BaseModel):
    """Isolated from provisioning and profile updates so a role change is
    always its own distinct, audited action. `root_admin` cannot be assigned
    via this endpoint - it is never reassigned via API in or out."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[UserRoleEnum.instructor, UserRoleEnum.teaching_assistant]


class StatusChangeRequest(BaseModel):
    """Optional free-text note stored on the audit event, never shown to the
    user whose access changed."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str | None) -> str | None:
        # Plain-text note: keep markup and control characters out of the audit
        # record. Rendering must still encode - this is defence in depth.
        if value is None:
            return None
        return _UNSAFE_REASON_CHARS.sub("", value).strip() or None


class UserListResponse(BaseModel):
    items: list[UserResponse]
    next_cursor: str | None = None
