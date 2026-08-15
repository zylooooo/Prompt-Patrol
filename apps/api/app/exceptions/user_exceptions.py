class EmailAlreadyExistsError(Exception):
    """A `users` row already exists for this email (active or soft-deleted)."""


class UserNotDeletedError(Exception):
    """Target user exists and is visible to the actor but isn't soft-deleted."""
