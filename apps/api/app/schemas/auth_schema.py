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
    email: str
    role: UserRoleEnum
    session: SessionResponse
