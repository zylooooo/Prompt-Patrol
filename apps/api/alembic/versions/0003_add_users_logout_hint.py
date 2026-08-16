"""add users.logout_hint

Stores Entra's `login_hint` claim so sign-out can replay it as `logout_hint` and
Microsoft does not ask "which account do you want to sign out from?".

Nullable with no backfill: the claim is only present once the `login_hint`
optional claim is enabled on the app registration (Token configuration), and
existing rows have never seen one. NULL simply means "no hint available", which
degrades to today's behaviour rather than failing.

Deliberately **not** exposed in `UserResponse`. It is opaque and not a
credential, but it names a person to Microsoft and has no business in a browser.

Revision ID: 0003_add_users_logout_hint
Revises: 0002_normalize_user_emails
Create Date: 2026-08-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_add_users_logout_hint"
down_revision = "0002_normalize_user_emails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("logout_hint", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "logout_hint")
