"""one row per CSV line: unique failures and checks per batch row

SQS redelivers messages (at least once). These indexes make a second
delivery of the same row a no-op in the Worker. DECISION LOG [0.33.0].

No duplicate clean-up on purpose: none have been seen, and if one exists
this migration should fail loudly rather than delete audit rows on a guess.

Revision ID: 0016_batch_row_idempotency
Revises: 0015_sessions_abs_expires_idx
Create Date: 2026-11-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_batch_row_idempotency"
down_revision = "0015_sessions_abs_expires_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_batch_row_failures_batch_row",
        "batch_row_failures",
        ["batch_id", "row_number"],
        unique=True,
        postgresql_where=sa.text("row_number > 0"),
    )
    op.add_column("checks", sa.Column("batch_row_number", sa.Integer(), nullable=True))
    op.create_index(
        "uq_checks_batch_row",
        "checks",
        ["batch_id", "batch_row_number"],
        # NULLs never collide in a unique index, so single checks are unaffected.
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_checks_batch_row", table_name="checks")
    op.drop_column("checks", "batch_row_number")
    op.drop_index("uq_batch_row_failures_batch_row", table_name="batch_row_failures")
