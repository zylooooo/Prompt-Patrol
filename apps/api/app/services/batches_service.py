import csv
import io
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Batch, BatchRowFailure, Check, StrictnessEnum, User

from .aws_clients import download_object, enqueue_row, purge_batch_messages

MAX_ROWS = 500
ANSWER_MIN_CHARS = 10
ANSWER_MAX_CHARS = 10000
EXTERNAL_REF_MAX_CHARS = 128
QUESTION_MAX_CHARS = 2000

REQUIRED_FIELDS = ("external_ref", "answer_text")


def _validate_row(fields: dict[str, str], requires_question_text: bool) -> str | None:
    """Returns a reason string if invalid, None if the row is good. One
    reason per row is enough - the instructor fixes and re-uploads, they
    don't need every rule violation enumerated per cell."""
    external_ref = fields.get("external_ref", "").strip()
    answer_text = fields.get("answer_text", "").strip()
    question_text = fields.get("question_text", "").strip()

    if not external_ref:
        return "external_ref is empty."
    if len(external_ref) > EXTERNAL_REF_MAX_CHARS:
        return f"external_ref is over {EXTERNAL_REF_MAX_CHARS} characters."
    if not answer_text:
        return "answer_text is empty."
    if len(answer_text) < ANSWER_MIN_CHARS:
        return f"answer_text is under {ANSWER_MIN_CHARS} characters."
    if len(answer_text) > ANSWER_MAX_CHARS:
        return f"answer_text is over {ANSWER_MAX_CHARS} characters."
    if question_text and len(question_text) > QUESTION_MAX_CHARS:
        return f"question_text is over {QUESTION_MAX_CHARS} characters."
    if requires_question_text and not question_text:
        return "question_text is required for this detector but was missing."
    return None


def parse_and_validate(
    text: str,
    column_mapping: dict[str, str] | None,
    requires_question_text: bool,
) -> tuple[list[dict], list[dict]]:
    """Authoritative server-side parse (spec Decision 3's second layer).
    column_mapping, if given, maps the instructor's literal header text to
    our field names (spec Decision 8) - applied here, not client-side, so
    the untouched original upload stays the source of truth in S3."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return [], [{"row_number": 0, "external_ref": None, "reason": "The file is empty."}]

    mapping = column_mapping or {}
    header_to_field = {h: mapping.get(h, h) for h in reader.fieldnames}
    missing = set(REQUIRED_FIELDS) - set(header_to_field.values())
    if missing:
        reason = f"Missing required column(s): {', '.join(sorted(missing))}."
        return [], [{"row_number": 0, "external_ref": None, "reason": reason}]

    rows: list[dict] = []
    failures: list[dict] = []
    # start=2: row_number is the line the instructor sees in their
    # spreadsheet, with the header occupying line 1.
    for row_number, raw_row in enumerate(reader, start=2):
        if row_number - 1 > MAX_ROWS:
            failures.append(
                {
                    "row_number": row_number,
                    "external_ref": None,
                    "reason": f"File exceeds the {MAX_ROWS}-row limit; row not processed.",
                }
            )
            continue

        fields = {header_to_field[h]: (v or "") for h, v in raw_row.items() if h in header_to_field}
        reason = _validate_row(fields, requires_question_text)
        if reason is not None:
            failures.append(
                {
                    "row_number": row_number,
                    "external_ref": fields.get("external_ref", "").strip() or None,
                    "reason": reason,
                }
            )
            continue

        rows.append(
            {
                "external_ref": fields["external_ref"].strip(),
                "answer_text": fields["answer_text"].strip(),
                "question_text": fields.get("question_text", "").strip() or None,
            }
        )

    return rows, failures


async def create_batch(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    upload_key: str,
    file_name: str,
    strictness: str,
    retain_answer: bool,
    column_mapping: dict[str, str] | None,
    requires_question_text: bool,
) -> Batch:
    text = download_object(upload_key)
    rows, failures = parse_and_validate(text, column_mapping, requires_question_text)

    batch = Batch(
        id=uuid.uuid4(),
        actor_id=actor_id,
        batch_file_name=file_name,
        strictness=StrictnessEnum(strictness),
        retain_answer=retain_answer,
        requires_question_text=requires_question_text,
        # Total of valid + rejected rows, not just enqueued ones - the
        # BatchProgress contract (openapi.yaml) guarantees
        # completed + failed + pending == row_total, and `failed` counts
        # every batch_row_failures row (pre-flight rejects and later DLQ
        # drains alike), so a pre-flight reject must already be counted here.
        row_total=len(rows) + len(failures),
    )
    db.add(batch)

    for failure in failures:
        db.add(
            BatchRowFailure(
                id=uuid.uuid4(),
                batch_id=batch.id,
                row_number=failure["row_number"],
                external_ref=failure["external_ref"],
                reason=failure["reason"],
            )
        )
    await db.commit()
    await db.refresh(batch)

    for row in rows:
        enqueue_row(
            {
                "batch_id": str(batch.id),
                "actor_id": str(actor_id),
                "strictness": strictness,
                "retain_answer": retain_answer,
                "external_ref": row["external_ref"],
                "answer_text": row["answer_text"],
                "question_text": row["question_text"],
            }
        )

    return batch


async def get_batch_progress(db: AsyncSession, actor: User, batch_id: uuid.UUID) -> dict | None:
    """None for both "no such batch" and "not yours" - same 404-not-403
    reasoning as get_check_by_id."""
    batch = (await db.execute(select(Batch).where(Batch.id == batch_id))).scalar_one_or_none()
    if batch is None or batch.actor_id != actor.id:
        return None

    completed = (
        await db.execute(select(func.count()).select_from(Check).where(Check.batch_id == batch_id))
    ).scalar_one()
    failed = (
        await db.execute(
            select(func.count()).select_from(BatchRowFailure).where(BatchRowFailure.batch_id == batch_id)
        )
    ).scalar_one()

    return {
        "batch": batch,
        "row_total": batch.row_total,
        "completed": completed,
        "failed": failed,
        "pending": max(batch.row_total - completed - failed, 0),
    }


async def cancel_batch(db: AsyncSession, actor: User, batch_id: uuid.UUID) -> Batch | None:
    """None for both "no such batch" and "not yours" - same 404-not-403
    reasoning as get_batch_progress. Idempotent: cancelling an
    already-cancelled (or already-finished) batch just returns it as-is
    rather than erroring - the Worker treats "cancelled" as a one-way flag,
    not a state machine with a wrong-transition to reject."""
    batch = (await db.execute(select(Batch).where(Batch.id == batch_id))).scalar_one_or_none()
    if batch is None or batch.actor_id != actor.id:
        return None

    if batch.cancelled_at is None:
        batch.cancelled_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(batch)
        purge_batch_messages(str(batch_id))
    return batch
