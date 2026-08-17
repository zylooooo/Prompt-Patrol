"""add users.display_name

A human-readable label for a person, so the roster can show "Amirah Rahman"
rather than the local part of an email address.

Nullable with no backfill, and deliberately **not** authoritative. An admin may
type a placeholder at provisioning time so the row is recognisable before that
person has ever signed in; Entra's `name` claim overwrites it on first login and
keeps it current thereafter (0006). Treating an admin-typed string as the truth
would let a mistyped name outlive a directory rename, with nobody able to see
that the two had diverged.

Named `display_name`, not `name`, to match `docs/openapi.yaml` and to say what it
is: a label for display, never an identity key. `email` and `entra_oid` remain the
only identifiers, and both keep their partial unique indexes from 0004. Nothing
about this column is unique, and nothing may look a user up by it.

Revision ID: 0005_add_users_display_name
Revises: 0004_user_lifecycle_status
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_add_users_display_name"
down_revision = "0004_user_lifecycle_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "display_name")
