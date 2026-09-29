"""add supervisions (many-to-many TA supervision)

`users.provisioned_by` was the only supervision edge, so a TA could have one
supervisor and moving them erased who invited them. This adds the join table
that replaces it and backfills one active link per live TA from
provisioned_by. provisioned_by itself is left untouched (it becomes
provenance only), so a downgrade loses only links made after the upgrade.

Backfill caveat: for a TA an admin moved, provisioned_by already holds the
current supervisor, so the link is right but earlier moves are not
recoverable. See DECISION LOG [0.21.0] in docs/openapi.yaml.

Revision ID: 0013_supervisions
Revises: 0012_user_first_login_at
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_supervisions"
down_revision = "0012_user_first_login_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supervisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("ta_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("instructor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_supervisions_ta_id", "supervisions", ["ta_id"])
    op.create_index("ix_supervisions_instructor_id", "supervisions", ["instructor_id"])
    op.create_index(
        "uq_supervisions_active_pair",
        "supervisions",
        ["ta_id", "instructor_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.execute(
        """
        INSERT INTO supervisions (id, ta_id, instructor_id)
        SELECT gen_random_uuid(), ta.id, ta.provisioned_by
        FROM users ta
        JOIN users i ON i.id = ta.provisioned_by
        WHERE ta.role = 'teaching_assistant' AND ta.status <> 'deleted'
          AND i.role = 'instructor' AND i.status <> 'deleted'
        """
    )


def downgrade() -> None:
    op.drop_index("uq_supervisions_active_pair", table_name="supervisions")
    op.drop_index("ix_supervisions_instructor_id", table_name="supervisions")
    op.drop_index("ix_supervisions_ta_id", table_name="supervisions")
    op.drop_table("supervisions")
