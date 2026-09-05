import asyncio
import base64
import binascii
import time
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import DetectorTimeoutError, DetectorUnavailableError
from models import AbstainReasonEnum, Check, StrictnessEnum, User, UserRoleEnum, VerdictEnum

from .detector_client import MODEL_VERSION, score_text

DETECTOR_TIMEOUT_SECONDS = 10

THRESHOLDS: dict[str, float] = {"lenient": 0.4, "standard": 0.5, "strict": 0.65}
TARGET_FPR: dict[str, float] = {"lenient": 0.05, "standard": 0.01, "strict": 0.001}
ABSTENTION_BAND = 0.08
MIN_ANSWER_WORDS = 10

DETECTOR_CAPABILITIES: dict = {
    "model_version": MODEL_VERSION,
    "requires_question_text": False,
    "min_answer_chars": 10,
    "max_answer_chars": 10000,
    "max_tokens_scored": 512,
    "strictness_levels": [{"level": level, "target_fpr": fpr} for level, fpr in TARGET_FPR.items()],
    "calibration_version": None,
    "supports_confidence": False,
    "supports_explanation": False,
    "supports_spans": False,
}


def _decide(raw_score: float, threshold: float, word_count: int) -> tuple[str, str | None]:
    if word_count < MIN_ANSWER_WORDS:
        return "uncertain", "answer_too_short"
    if abs(raw_score - threshold) <= ABSTENTION_BAND:
        return "uncertain", "score_in_abstention_band"
    return ("ai_generated" if raw_score > threshold else "human_written"), None


async def create_check(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    answer_text: str,
    question_text: str | None,
    external_ref: str | None,
    strictness: str,
    retain_answer: bool,
    batch_id: uuid.UUID | None = None,
    batch_file_name: str | None = None,
) -> Check:
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(score_text(answer_text), timeout=DETECTOR_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise DetectorTimeoutError from exc
    except Exception as exc:
        raise DetectorUnavailableError from exc
    latency_ms = int((time.perf_counter() - start) * 1000)

    threshold = THRESHOLDS[strictness]
    word_count = len(answer_text.split())
    verdict, abstain_reason = _decide(result.raw_score, threshold, word_count)

    check = Check(
        actor_id=actor_id,
        batch_id=batch_id,
        batch_file_name=batch_file_name,
        external_ref=external_ref,
        verdict=VerdictEnum(verdict),
        raw_score=result.raw_score,
        confidence=None,
        abstain_reason=AbstainReasonEnum(abstain_reason) if abstain_reason else None,
        truncated=result.truncated,
        model_version=MODEL_VERSION,
        calibration_version=None,
        strictness_applied=StrictnessEnum(strictness),
        threshold_applied=threshold,
        target_fpr=TARGET_FPR[strictness],
        used_question_text=False,
        # The judgement is recorded either way; only the text is withheld.
        answer_text=answer_text if retain_answer else None,
        question_text=question_text,
        answer_char_len=len(answer_text),
        retain_answer=retain_answer,
        latency_ms=latency_ms,
    )
    db.add(check)
    await db.commit()
    await db.refresh(check)
    return check


def _may_read_any_check(actor: User) -> bool:
    """Checks carry student answer text, so the rule is narrower than the user
    directory's: you read what you ran, and a root admin reads everything.
    Widening this later is backwards-compatible; narrowing it would not be."""
    return actor.role == UserRoleEnum.root_admin


def _encode_cursor(check_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(str(check_id).encode()).decode()


def _decode_cursor(cursor: str) -> uuid.UUID:
    try:
        return uuid.UUID(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("Invalid cursor") from exc


async def list_checks(
    db: AsyncSession,
    actor: User,
    limit: int = 50,
    cursor: str | None = None,
    actor_id: uuid.UUID | None = None,
    verdict: VerdictEnum | None = None,
    batch_id: uuid.UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> tuple[list[Check], str | None]:
    """Newest first. Keyset-paginated on `created_at, id` rather than `id`
    alone: ids are random UUIDs, so paging by id would hand back rows in an
    order nobody asked for and the history page reads chronologically.

    `actor_id` is only honoured for a caller who may already read any check
    (root_admin) - silently ignored otherwise. A 403 on someone else's id
    would confirm that id exists, so override rather than reject."""
    query = select(Check)
    if not _may_read_any_check(actor):
        query = query.where(Check.actor_id == actor.id)
    elif actor_id is not None:
        query = query.where(Check.actor_id == actor_id)

    if verdict is not None:
        query = query.where(Check.verdict == verdict)
    if batch_id is not None:
        query = query.where(Check.batch_id == batch_id)
    if created_from is not None:
        query = query.where(Check.created_at >= created_from)
    if created_to is not None:
        query = query.where(Check.created_at <= created_to)

    if cursor is not None:
        anchor_id = _decode_cursor(cursor)
        anchor = (await db.execute(select(Check).where(Check.id == anchor_id))).scalar_one_or_none()
        if anchor is None:
            raise ValueError("Invalid cursor")
        # Strictly older than the anchor, with id breaking ties on equal
        # timestamps so a page boundary cannot repeat or skip a row.
        query = query.where(
            (Check.created_at < anchor.created_at)
            | ((Check.created_at == anchor.created_at) & (Check.id < anchor.id))
        )

    query = query.order_by(Check.created_at.desc(), Check.id.desc()).limit(limit + 1)
    rows = list((await db.execute(query)).scalars().all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].id)
    return rows, next_cursor


async def get_check_by_id(db: AsyncSession, actor: User, check_id: uuid.UUID) -> Check | None:
    """`None` for both "no such check" and "not yours", so the endpoint cannot
    be used to discover that a check exists."""
    check = (await db.execute(select(Check).where(Check.id == check_id))).scalar_one_or_none()
    if check is None:
        return None
    if not _may_read_any_check(actor) and check.actor_id != actor.id:
        return None
    return check
