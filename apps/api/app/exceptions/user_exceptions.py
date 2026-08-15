class EmailAlreadyExistsError(Exception):
    """A `users` row already exists for this email (active or soft-deleted)."""
