"""add the checks table - the first user-owned business resource

Until now `create_check` scored an answer and returned it without writing
anything, so screening history lived in the browser's localStorage. That made a
check a property of one device: clear the browser and the record was gone, open
the app on another machine and it had never happened.

Three choices recorded here because they are hard to reverse:

1. **Every detector-dependent value is stored, not re-derived.** `model_version`,
   `threshold_applied`, `target_fpr` and `strictness_applied` are columns, not
   lookups against whatever `services/checks.py` says today. A check is a record
   of a judgement someone acted on; recalibrating the detector must not silently
   rewrite what a past verdict was based on.

2. **No `batches` table.** A batch is rows sharing `batch_id`, assigned by the
   client. The server has no batch concept - `POST /api/checks` scores one
   answer - and a table whose only job is to hold an id it did not generate
   would be a second source of truth for grouping. `batch_file_name` is
   denormalised onto every row for the same reason: it is the only part of a
   run that cannot be derived from the rows themselves.

3. **`answer_text` is nullable and the row is written either way.** A submitter
   passing `retain_answer: false` gets a stored judgement with no stored text.
   Skipping the row instead would leave history with holes that look like the
   check never happened.

Written by hand rather than `--autogenerate`: this repo has known model/migration
drift (see 06-database.md), so generated output proposes spurious drops.

Revision ID: 0006_add_checks
Revises: 0005_add_users_display_name
Create Date: 2026-08-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_add_checks"
down_revision = "0005_add_users_display_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("batch_file_name", sa.String(length=255), nullable=True),
        sa.Column("external_ref", sa.String(length=128), nullable=True),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("raw_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("abstain_reason", sa.String(), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("calibration_version", sa.String(), nullable=True),
        sa.Column("strictness_applied", sa.String(), nullable=False),
        sa.Column("threshold_applied", sa.Float(), nullable=False),
        sa.Column("target_fpr", sa.Float(), nullable=True),
        sa.Column("used_question_text", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # The history page's only query: this author's checks, paged. Composite
    # because the scope and the ordering always travel together.
    op.create_index("ix_checks_actor_id_created_at", "checks", ["actor_id", "created_at"])
    op.create_index("ix_checks_batch_id", "checks", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_checks_batch_id", table_name="checks")
    op.drop_index("ix_checks_actor_id_created_at", table_name="checks")
    op.drop_table("checks")
