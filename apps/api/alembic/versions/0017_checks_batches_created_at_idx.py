"""index checks.created_at and batches.created_at

The daily 90-day retention purge (scripts.purge_checks, DECISION LOG
[0.34.0]) filters on these columns alone; ix_checks_actor_id_created_at
leads with actor_id, so it cannot serve a global age cut.

Revision ID: 0017_created_at_retention_idx
Revises: 0016_batch_row_idempotency
Create Date: 2026-11-09
"""

from alembic import op

revision = "0017_created_at_retention_idx"
down_revision = "0016_batch_row_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_checks_created_at", "checks", ["created_at"])
    op.create_index("ix_batches_created_at", "batches", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_batches_created_at", table_name="batches")
    op.drop_index("ix_checks_created_at", table_name="checks")
