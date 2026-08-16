class EmailAlreadyExistsError(Exception):
    """A live `users` row already exists for this email. Deleted rows do not
    reserve an address, so the same person can be provisioned again."""


class UserNotFoundError(Exception):
    """No `users` row with this id, at any lifecycle status."""


class InvalidStatusTransitionError(Exception):
    """The requested lifecycle move is not permitted from the current status."""
