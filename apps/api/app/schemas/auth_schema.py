import uuid
from datetime import datetime

from pydantic import BaseModel

from models import UserRoleEnum


class SessionResponse(BaseModel):
    expires_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    expires_in_seconds: int
    capped: bool
    idle_timeout_seconds: int


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    # Null until the person picks one; the SPA prompts for it.
    display_name: str | None
    role: UserRoleEnum
    # Instructors currently supervising this user - the SPA's screening gate.
    supervisor_ids: list[uuid.UUID]
    session: SessionResponse
