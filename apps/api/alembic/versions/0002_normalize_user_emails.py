"""normalize user emails to trimmed lowercase

Brings rows written before `services.users_service.normalize_email` existed into
the one form the application now stores and matches on. Without this pass, a row
provisioned as `Ada@smu.edu.sg` stays unmatchable: every lookup normalises the
incoming address to lowercase, and the stored value never will be.

**This migration fails loudly on a case-collision.** If two rows differ only by
case (`ada@…` and `Ada@…`), lowercasing both violates the UNIQUE constraint on
`users.email` and the migration aborts with an IntegrityError. That is
deliberate — those are two accounts for one person, possibly with different
roles and different `provisioned_by`, and only an operator can decide which one
survives. Find them with:

    SELECT lower(email), count(*), array_agg(id)
    FROM users GROUP BY lower(email) HAVING count(*) > 1;

Revision ID: 0002_normalize_user_emails
Revises: 0001_users_and_sessions
Create Date: 2026-08-16
"""

from alembic import op

revision = "0002_normalize_user_emails"
down_revision = "0001_users_and_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET email = lower(btrim(email)) WHERE email <> lower(btrim(email))")


def downgrade() -> None:
    # Intentionally a no-op. The original casing is not recorded anywhere, so
    # there is nothing to restore. Lowercased addresses stay valid under the old
    # code, which compared exactly — they are simply matchable by fewer inputs.
    pass
