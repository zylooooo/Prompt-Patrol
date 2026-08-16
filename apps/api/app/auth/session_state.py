import enum
from dataclasses import dataclass
from datetime import datetime

from models import User


class SessionFailure(str, enum.Enum):
    not_signed_in = "not_signed_in"
    session_unknown = "session_unknown"
    session_revoked = "session_revoked"
    session_expired = "session_expired"
    session_ended = "session_ended"
    account_deactivated = "account_deactivated"


@dataclass(frozen=True)
class ActiveSession:
    user: User
    expires_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime

    @property
    def capped(self) -> bool:
        return self.absolute_expires_at <= self.idle_expires_at
