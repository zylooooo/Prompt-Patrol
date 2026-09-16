"""add batches and batch_row_failures

Real batches table, replacing the "batch is rows sharing an id" assumption.
checks rows stay write-once - never created pending. See DECISION LOG
[0.13.0] in docs/openapi.yaml and
docs/superpowers/specs/2026-09-09-batches-module-design.md.

Revision ID: 0010_batches
Revises: 0009_user_role_events
Create Date: 2026-09-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_batches"
down_revision = "0009_user_role_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("batch_file_name", sa.String(255), nullable=False),
        sa.Column("strictness", sa.String(), nullable=False),
        sa.Column("retain_answer", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("requires_question_text", sa.Boolean(), nullable=False),
        sa.Column("row_total", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "batch_row_failures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("batches.id"), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("external_ref", sa.String(128), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_batch_row_failures_batch_id", "batch_row_failures", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_batch_row_failures_batch_id", table_name="batch_row_failures")
    op.drop_table("batch_row_failures")
    op.drop_table("batches")
