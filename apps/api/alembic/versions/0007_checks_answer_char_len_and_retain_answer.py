"""checks: add answer_char_len and retain_answer

Both were in the illustrative DDL sketch at the bottom of openapi.yaml from the
start (0006's checks table matched it otherwise) but never made it into the
model or the table.

answer_char_len is captured at write time so it survives a future purge of
answer_text - E3's reliability-vs-answer-length analysis depends on the length
outliving the text. retain_answer is stored verbatim rather than re-derived
from `answer_text IS NULL`: that inference only holds until a purge job
exists, after which a purged row and a never-retained one look identical
without this column.

Both are NOT NULL, so existing rows are backfilled first:
- retain_answer = (answer_text IS NOT NULL). Valid for every row that exists
  today because no purge job has ever run - NULL text only ever meant the
  submitter opted out.
- answer_char_len = LENGTH(answer_text), defaulting to 0 where answer_text is
  NULL. Those rows' true original length was never captured and cannot be
  recovered retroactively; going forward every row captures it before any
  conditional nulling.

Revision ID: 0007_checks_char_len_retain
Revises: 0006_add_checks
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_checks_char_len_retain"
down_revision = "0006_add_checks"
branch_labels = None
depends_on = None

checks = sa.table(
    "checks",
    sa.column("answer_text", sa.Text()),
    sa.column("answer_char_len", sa.Integer()),
    sa.column("retain_answer", sa.Boolean()),
)


def upgrade() -> None:
    op.add_column("checks", sa.Column("answer_char_len", sa.Integer(), nullable=True))
    op.add_column(
        "checks", sa.Column("retain_answer", sa.Boolean(), nullable=True, server_default=sa.true())
    )

    op.execute(
        checks.update().values(
            answer_char_len=sa.func.coalesce(sa.func.length(checks.c.answer_text), 0),
            retain_answer=checks.c.answer_text.isnot(None),
        )
    )

    with op.batch_alter_table("checks") as batch_op:
        batch_op.alter_column("answer_char_len", nullable=False)
        batch_op.alter_column("retain_answer", nullable=False, server_default=None)


def downgrade() -> None:
    op.drop_column("checks", "retain_answer")
    op.drop_column("checks", "answer_char_len")
