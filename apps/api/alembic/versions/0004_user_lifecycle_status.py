"""replace users.deleted_at with an authoritative lifecycle status

Before: one nullable timestamp meant both "deactivated" and "deleted", and the
backend called it deletion while the UI called it deactivation.

After: `users.status` is the only lifecycle field - active | deactivated |
deleted - and `user_status_events` records who changed it, when, from what, to
what, and why.

Two deliberate choices recorded here because they are hard to reverse:

1. `deleted_at` is DROPPED rather than kept alongside `status`. Two fields
   describing one thing can disagree, and the combination `status = 'active'`
   with `deleted_at` set has no meaning. Timestamps now live in the event table,
   which is append-only and answers "when" more precisely anyway.

2. The UNIQUE constraints on `email` and `entra_oid` become **partial** indexes
   covering non-deleted rows only. A deleted row keeps its real address for
   attribution but stops reserving it, so the same person can be provisioned
   again later. Without this, deletion is irreversible AND permanently blocks
   that identity - the worst of both.

Backfill maps every existing `deleted_at IS NOT NULL` row to **deactivated**,
not deleted. Those rows were created by an operation the UI labelled
"Deactivate", so deactivated is what they actually mean. Mapping them to
`deleted` would silently escalate reversible offboarding into permanent removal.
No seed event rows are written for them: nothing recorded who did it or why, and
inventing an actor would be worse than an honest gap.

Revision ID: 0004_user_lifecycle_status
Revises: 0003_add_users_logout_hint
Create Date: 2026-08-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_user_lifecycle_status"
down_revision = "0003_add_users_logout_hint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
    )
    op.execute("UPDATE users SET status = 'deactivated' WHERE deleted_at IS NOT NULL")

    # Drop the whole-table uniqueness before the partial indexes replace it,
    # or a re-provisioned identity still collides with its deleted predecessor.
    op.drop_constraint("users_email_key", "users", type_="unique")
    op.drop_constraint("users_entra_oid_key", "users", type_="unique")
    op.create_index(
        "uq_users_email_live",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("status <> 'deleted'"),
    )
    op.create_index(
        "uq_users_entra_oid_live",
        "users",
        ["entra_oid"],
        unique=True,
        postgresql_where=sa.text("status <> 'deleted'"),
    )

    op.drop_column("users", "deleted_at")

    op.create_table(
        "user_status_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("from_status", sa.String(), nullable=False),
        sa.Column("to_status", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_user_status_events_user_id", "user_status_events", ["user_id"])


def downgrade() -> None:
    # Loses every event row and collapses deactivated/deleted back into one
    # timestamp. Both statuses map to "not null" because the old column could not
    # tell them apart - going back down is genuinely lossy.
    op.drop_index("ix_user_status_events_user_id", table_name="user_status_events")
    op.drop_table("user_status_events")

    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET deleted_at = now() WHERE status <> 'active'")

    op.drop_index("uq_users_entra_oid_live", table_name="users")
    op.drop_index("uq_users_email_live", table_name="users")
    op.create_unique_constraint("users_email_key", "users", ["email"])
    op.create_unique_constraint("users_entra_oid_key", "users", ["entra_oid"])

    op.drop_column("users", "status")
