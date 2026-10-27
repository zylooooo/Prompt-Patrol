class EmailAlreadyExistsError(Exception):
    """A live `users` row already exists for this email. Deleted rows do not
    reserve an address, so the same person can be provisioned again."""


class UserNotFoundError(Exception):
    """No `users` row with this id, at any lifecycle status."""


class InvalidStatusTransitionError(Exception):
    """The requested lifecycle move is not permitted from the current status."""


class InvalidSupervisorError(Exception):
    """The proposed supervisor cannot hold that role: missing, not an instructor,
    not active, or the assistant themselves.

    The message is returned to the caller as-is, so it must be a user-facing
    sentence. Safe because only root_admin reaches it, and root_admin can
    already see every user - there is nothing to enumerate."""


class CannotAddTeachingAssistantError(Exception):
    """An instructor typed an email that is not new and not an active TA."""
