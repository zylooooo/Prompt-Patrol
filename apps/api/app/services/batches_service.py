import csv
import io
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Batch, BatchRowFailure, Check, StrictnessEnum, User, UserRoleEnum

from .aws_clients import download_object, enqueue_row, purge_batch_messages

logger = logging.getLogger(__name__)

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
    """Authoritative server-side parse. column_mapping, if given, maps the 
    instructor's literal header text to the internal field names. 
    The mapping is applied here, not client-side, so the untouched original 
    upload stays the source of truth in S3."""
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
    # start=2: since the header is at row 1
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
        # Total of valid + rejected rows, not just enqueued ones.
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
    logger.info(
        "Batch %s created by actor %s: %d rows queued, %d rejected at parse time.",
        batch.id, actor_id, len(rows), len(failures),
    )

    enqueue_failed = 0
    for row in rows:
        try:
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
        except Exception:
            # SQS is unavailable/throttled partway through. The row never
            # reaches the Worker, so it must count as `failed` rather than
            # sit as `pending` forever.
            logger.exception(
                "Failed to enqueue row %r for batch %s.", row["external_ref"], batch.id
            )
            enqueue_failed += 1
            db.add(
                BatchRowFailure(
                    id=uuid.uuid4(),
                    batch_id=batch.id,
                    row_number=0,
                    external_ref=row["external_ref"],
                    reason="Failed to queue row for processing.",
                )
            )
    if enqueue_failed:
        logger.warning(
            "Batch %s: %d of %d rows failed to enqueue.", batch.id, enqueue_failed, len(rows)
        )
        await db.commit()

    return batch


def _may_access_any_batch(actor: User) -> bool:
    """Same override as checks_service._may_read_any_check - a root admin
    can see/cancel any instructor's batch, everyone else only their own."""
    return actor.role == UserRoleEnum.root_admin


async def get_batch_progress(db: AsyncSession, actor: User, batch_id: uuid.UUID) -> dict | None:
    """None for both "no such batch" and batches that are not authorized for this actor."""
    batch = (await db.execute(select(Batch).where(Batch.id == batch_id))).scalar_one_or_none()
    if batch is None or (batch.actor_id != actor.id and not _may_access_any_batch(actor)):
        return None

    completed = (
        await db.execute(select(func.count()).select_from(Check).where(Check.batch_id == batch_id))
    ).scalar_one()
    failures = list(
        (
            await db.execute(
                select(BatchRowFailure)
                .where(BatchRowFailure.batch_id == batch_id)
                .order_by(BatchRowFailure.created_at)
            )
        )
        .scalars()
        .all()
    )

    return {
        "batch": batch,
        "row_total": batch.row_total,
        "completed": completed,
        "failed": len(failures),
        "pending": max(batch.row_total - completed - len(failures), 0),
        "failures": failures,
    }


async def cancel_batch(db: AsyncSession, actor: User, batch_id: uuid.UUID) -> Batch | None:
    """None for both "no such batch" and "not yours". Idempotent: cancelling an
    already-cancelled (or already-finished) batch just returns it as-is
    rather than erroring. The Worker treats "cancelled" as a one-way flag,
    not a state machine with a wrong-transition to reject."""
    batch = (await db.execute(select(Batch).where(Batch.id == batch_id))).scalar_one_or_none()
    if batch is None or (batch.actor_id != actor.id and not _may_access_any_batch(actor)):
        return None

    if batch.cancelled_at is None:
        batch.cancelled_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(batch)
        purged = purge_batch_messages(str(batch_id))
        logger.info("Batch %s cancelled by actor %s: %d queued rows purged.", batch_id, actor.id, purged)
    return batch
