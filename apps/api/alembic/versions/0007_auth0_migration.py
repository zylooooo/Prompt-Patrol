"""swap identity provider from Entra ID to Auth0

The sponsor could not get the app whitelisted (app registration + admin
consent) in the university's own Entra tenant. Auth0 replaces Entra as the
OIDC identity broker only - the BFF pattern, opaque session cookie, and
invite-first provisioning model are all unchanged. See DECISION LOG [0.6.0]
in docs/openapi.yaml.

`entra_oid` -> `auth0_sub`: same nullable column, same partial-uniqueness
semantics (unique among non-deleted rows), just holding Auth0's `sub` claim
instead of Entra's `oid`. Pre-launch, no real logins exist yet, so a plain
rename is safe - there is nothing to re-bind.

`logout_hint` is dropped outright, not renamed. It stored Entra's `login_hint`
claim for replay at sign-out to suppress Entra's account-picker prompt. Auth0
does not implement RP-Initiated Logout the way Entra did; its `/v2/logout`
endpoint takes no per-user hint at all, so there is nothing to store.

Revision ID: 0007_auth0_migration
Revises: 0006_add_checks
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_auth0_migration"
down_revision = "0006_add_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_users_entra_oid_live", table_name="users")
    op.alter_column("users", "entra_oid", new_column_name="auth0_sub")
    op.create_index(
        "uq_users_auth0_sub_live",
        "users",
        ["auth0_sub"],
        unique=True,
        postgresql_where=sa.text("status <> 'deleted'"),
    )

    op.drop_column("users", "logout_hint")


def downgrade() -> None:
    op.add_column("users", sa.Column("logout_hint", sa.String(), nullable=True))

    op.drop_index("uq_users_auth0_sub_live", table_name="users")
    op.alter_column("users", "auth0_sub", new_column_name="entra_oid")
    op.create_index(
        "uq_users_entra_oid_live",
        "users",
        ["entra_oid"],
        unique=True,
        postgresql_where=sa.text("status <> 'deleted'"),
    )
