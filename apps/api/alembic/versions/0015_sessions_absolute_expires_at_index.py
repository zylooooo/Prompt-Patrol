"""index sessions.absolute_expires_at

The daily global purge filters on this column alone; without an index it
scans the whole sessions table.

Revision ID: 0015_sessions_absolute_expires_at_index
Revises: 0014_user_reprovisioned_at
Create Date: 2026-10-18
"""

from alembic import op

revision = "0015_sessions_absolute_expires_at_index"
down_revision = "0014_user_reprovisioned_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_sessions_absolute_expires_at", "sessions", ["absolute_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_sessions_absolute_expires_at", table_name="sessions")
