from .auth_exceptions import Auth0ProvisioningError
from .detector_exceptions import DetectorTimeoutError, DetectorUnavailableError
from .handlers import error_response, register_exception_handlers
from .user_exceptions import (
    CannotAddTeachingAssistantError,
    EmailAlreadyExistsError,
    EmailDomainNotAllowedError,
    InvalidStatusTransitionError,
    InvalidSupervisorError,
    UserNotFoundError,
)

__all__ = [
    "Auth0ProvisioningError",
    "CannotAddTeachingAssistantError",
    "EmailAlreadyExistsError",
    "EmailDomainNotAllowedError",
    "InvalidStatusTransitionError",
    "InvalidSupervisorError",
    "UserNotFoundError",
    "DetectorTimeoutError",
    "DetectorUnavailableError",
    "error_response",
    "register_exception_handlers",
]
