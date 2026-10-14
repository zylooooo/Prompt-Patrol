"""add users.reprovisioned_at

Re-provisioning a deleted email reuses its row and id, and checks and batches
are owned by that id, so the new holder of the address inherited the previous
holder's history. Stamped when a deleted row is re-provisioned; reads of the
caller's own checks and batches skip rows created before it. Backfilled from
the latest `deleted -> active` status event, which every past re-provisioning
wrote.

Revision ID: 0014_user_reprovisioned_at
Revises: 0013_supervisions
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_user_reprovisioned_at"
down_revision = "0013_supervisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("reprovisioned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE users SET reprovisioned_at = "
        "(SELECT MAX(e.created_at) FROM user_status_events e "
        "WHERE e.user_id = users.id AND e.from_status = 'deleted' AND e.to_status = 'active')"
    )


def downgrade() -> None:
    op.drop_column("users", "reprovisioned_at")
