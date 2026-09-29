"""add users.first_login_at

Stamped once by the first successful sign-in; null means the invite is still
pending. Backfilled from each existing user's earliest session so nobody who
already uses the tool shows up as pending. See DECISION LOG [0.19.0] in
docs/openapi.yaml.

Revision ID: 0012_user_first_login_at
Revises: 0011_batch_cancellation
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_user_first_login_at"
down_revision = "0011_batch_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("first_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE users SET first_login_at = "
        "(SELECT MIN(sessions.created_at) FROM sessions WHERE sessions.user_id = users.id)"
    )


def downgrade() -> None:
    op.drop_column("users", "first_login_at")
