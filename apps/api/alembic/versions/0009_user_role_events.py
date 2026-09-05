"""add user_role_events

PATCH /api/users/{id}/role (contract only, until now) promised it is audited
- actor_id, old_role, new_role, timestamp - but no event table existed. This
adds one, same shape as user_status_events, kept separate rather than merged:
UserStatusEnum and UserRoleEnum don't share column shape, and the contract's
own rationale for giving role changes a distinct endpoint ("always its own
distinct, audited action") argues against folding it into the status table
via a discriminator. See DECISION LOG [0.11.0] in docs/openapi.yaml.

Revision ID: 0009_user_role_events
Revises: 0008_checks_char_len_retain
Create Date: 2026-09-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_user_role_events"
down_revision = "0008_checks_char_len_retain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_role_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("from_role", sa.String(), nullable=False),
        sa.Column("to_role", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_user_role_events_user_id", "user_role_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_role_events_user_id", table_name="user_role_events")
    op.drop_table("user_role_events")
