"""add batches.cancelled_at

Lets an instructor stop an in-flight batch. The Worker checks this before
scoring each row and records a batch_row_failure instead once it's set,
rather than deleting/racing already-enqueued SQS messages. See DECISION LOG
[0.14.0] in docs/openapi.yaml.

Revision ID: 0011_batch_cancellation
Revises: 0010_batches
Create Date: 2026-09-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_batch_cancellation"
down_revision = "0010_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "batches",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("batches", "cancelled_at")
