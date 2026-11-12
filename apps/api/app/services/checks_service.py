import asyncio
import base64
import binascii
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
from sqlalchemy import CursorResult, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import DetectorTimeoutError, DetectorUnavailableError
from models import AbstainReasonEnum, Batch, BatchRowFailure, Check, StrictnessEnum, User, UserRoleEnum, VerdictEnum

from .detector_client import (
    CALIBRATION_VERSION,
    MODEL_VERSION,
    Score,
    reported_calibration_version,
    reported_model_version,
    score_text,
)

logger = logging.getLogger(__name__)

DETECTOR_TIMEOUT_SECONDS = 10

# For an uncalibrated model (the roberta baseline): one threshold per strictness level and a wide band.
UNCALIBRATED_THRESHOLDS: dict[str, float] = {"lenient": 0.4, "standard": 0.5, "strict": 0.65}
UNCALIBRATED_ABSTENTION_BAND = 0.08
TARGET_FPR: dict[str, float] = {"lenient": 0.05, "standard": 0.01, "strict": 0.001}

# A calibrated detector reports its own threshold and band with every score (Score.threshold / abstention_band), and
# those are what _settings_for applies. Only the 1% FPR threshold has been fitted for any model, so until the 5% and
# 0.1% ones are, every strictness level uses that one threshold so no level behaves wildly.
#
# DETECTOR_THRESHOLD and ABSTENTION_BAND are only the fallback for a detector too old to report them (and the e2e
# stub). Kept under the old names below so a fallback keeps working exactly as before.
_ENV_THRESHOLD = os.getenv("DETECTOR_THRESHOLD")
_ENV_BAND = os.getenv("ABSTENTION_BAND")
THRESHOLDS: dict[str, float] = (
    dict.fromkeys(UNCALIBRATED_THRESHOLDS, float(_ENV_THRESHOLD)) if _ENV_THRESHOLD else dict(UNCALIBRATED_THRESHOLDS)
)
ABSTENTION_BAND = float(_ENV_BAND) if _ENV_BAND else UNCALIBRATED_ABSTENTION_BAND
MIN_ANSWER_WORDS = 10


# Feature flag: off until per-level thresholds are fitted (see above). Off, only "standard" is offered
# (GET /api/detector) and accepted (POST checks/batches); the SPA hides the picker when one level is
# left. STRICTNESS_ENABLED=true brings all three back with no frontend release.
STRICTNESS_ENABLED = os.getenv("STRICTNESS_ENABLED", "false").lower() == "true"


def strictness_levels() -> list[str]:
    return list(TARGET_FPR) if STRICTNESS_ENABLED else ["standard"]


def detector_capabilities() -> dict:
    """What GET /api/detector returns. The model and calibration are the ones the detector last reported (see
    detector_client._remember), so they name what is actually running."""
    return {
        "model_version": reported_model_version(),
        "requires_question_text": False,
        "min_answer_chars": 10,
        "max_answer_chars": 10000,
        "max_tokens_scored": 512,
        "strictness_levels": [{"level": level, "target_fpr": TARGET_FPR[level]} for level in strictness_levels()],
        "calibration_version": reported_calibration_version(),
        "supports_confidence": False,
        "supports_explanation": False,
        "supports_spans": False,
    }

@dataclass(frozen=True)
class AppliedSettings:
    """How one score is read: recorded on the check, so every verdict names the model and the numbers behind it."""

    model_version: str
    calibration_version: str | None
    threshold: float
    abstention_band: float


# (setting, environment value, reported value) already warned about, so a mismatch is logged once, not per check
_warned: set[tuple[str, str, str]] = set()


def _warn_if_env_disagrees(setting: str, env_value: str | None, reported: object, same: bool) -> None:
    if env_value is None or same:
        return
    key = (setting, env_value, str(reported))
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(
        "The detector reports %s=%s but the API's environment sets %s; using the detector's. "
        "Remove the stale variable (it is only a fallback for detectors that don't report their calibration).",
        setting,
        reported,
        env_value,
    )


def _settings_for(result: Score, strictness: str) -> AppliedSettings:
    """The detector's own calibration when it reports one, so a threshold fitted for one model is never applied to
    another model's scores. A detector too old to report falls back to the environment, exactly as before."""
    if result.model_version is None:
        return AppliedSettings(
            model_version=MODEL_VERSION,
            calibration_version=CALIBRATION_VERSION if CALIBRATION_VERSION else None,
            threshold=THRESHOLDS[strictness],
            abstention_band=ABSTENTION_BAND,
        )

    if result.threshold is not None:
        threshold = result.threshold
        _warn_if_env_disagrees(
            "threshold", _ENV_THRESHOLD, threshold, _ENV_THRESHOLD is not None and float(_ENV_THRESHOLD) == threshold
        )
    else:
        threshold = UNCALIBRATED_THRESHOLDS[strictness]
    band = result.abstention_band if result.abstention_band is not None else UNCALIBRATED_ABSTENTION_BAND
    _warn_if_env_disagrees("abstention_band", _ENV_BAND, band, _ENV_BAND is not None and float(_ENV_BAND) == band)
    env_model = os.getenv("DETECTOR_MODEL_VERSION")
    _warn_if_env_disagrees("model_version", env_model, result.model_version, env_model == result.model_version)
    env_calibration = os.getenv("DETECTOR_CALIBRATION_VERSION") or None
    _warn_if_env_disagrees(
        "calibration_version",
        env_calibration,
        result.calibration_version,
        env_calibration == result.calibration_version,
    )
    return AppliedSettings(
        model_version=result.model_version,
        calibration_version=result.calibration_version,
        threshold=threshold,
        abstention_band=band,
    )


# TODO: the decision logic for wether each answer will be flagged. This can be tweaked in the future.
def _decide(
    raw_score: float, threshold: float, word_count: int, abstention_band: float | None = None
) -> tuple[str, str | None]:
    band = ABSTENTION_BAND if abstention_band is None else abstention_band
    if word_count < MIN_ANSWER_WORDS:
        return "uncertain", "answer_too_short"
    if abs(raw_score - threshold) <= band:
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
    batch_row_number: int | None = None,
) -> Check:
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(score_text(answer_text), timeout=DETECTOR_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        logger.warning("Detector timed out after %ds for actor %s.", DETECTOR_TIMEOUT_SECONDS, actor_id)
        raise DetectorTimeoutError from exc
    except httpx.HTTPError as exc:
        logger.warning("Detector unavailable for actor %s: %s", actor_id, exc)
        raise DetectorUnavailableError from exc
    latency_ms = int((time.perf_counter() - start) * 1000)

    applied = _settings_for(result, strictness)
    word_count = len(answer_text.split())
    verdict, abstain_reason = _decide(result.raw_score, applied.threshold, word_count, applied.abstention_band)

    check = Check(
        actor_id=actor_id,
        batch_id=batch_id,
        batch_file_name=batch_file_name,
        batch_row_number=batch_row_number,
        external_ref=external_ref,
        verdict=VerdictEnum(verdict),
        raw_score=result.raw_score,
        confidence=None,
        abstain_reason=AbstainReasonEnum(abstain_reason) if abstain_reason else None,
        truncated=result.truncated,
        model_version=applied.model_version,
        calibration_version=applied.calibration_version,
        strictness_applied=StrictnessEnum(strictness),
        threshold_applied=applied.threshold,
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
        query = query.where(actor.owned_by_clause(Check))
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
            (Check.created_at < anchor.created_at) | ((Check.created_at == anchor.created_at) & (Check.id < anchor.id))
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
    if not _may_read_any_check(actor) and not actor.owns(check.actor_id, check.created_at):
        return None
    return check


# Sponsor's retention policy: check history is kept for 3 months, then deleted.
CHECK_RETENTION = timedelta(days=90)


# Hard-deletes every check, batch and batch failure past retention, in chunks.
async def purge_expired_checks(db: AsyncSession, batch_size: int = 500) -> tuple[int, int]:
    """Returns (checks deleted, batches deleted).

    A batch goes as one unit, aged by its own created_at: its progress is
    counted from its checks and failures, so deleting only some of them would
    leave a batch that reads as pending forever. The second loop then takes
    single checks, and checks whose batch row no longer exists. It skips
    checks of a surviving batch: the API and Worker clocks can disagree by a
    few seconds, so such a check can look older than the cutoff while its
    batch does not.
    """
    # Both cuts are served by ix_checks_created_at / ix_batches_created_at
    cutoff = datetime.now(UTC) - CHECK_RETENTION
    checks = batches = 0
    while True:
        ids = list((await db.execute(select(Batch.id).where(Batch.created_at < cutoff).limit(batch_size))).scalars())
        if not ids:
            break
        await db.execute(delete(BatchRowFailure).where(BatchRowFailure.batch_id.in_(ids)))
        result = cast(CursorResult, await db.execute(delete(Check).where(Check.batch_id.in_(ids))))
        await db.execute(delete(Batch).where(Batch.id.in_(ids)))
        await db.commit()
        checks += result.rowcount
        batches += len(ids)
    while True:
        result = cast(
            CursorResult,
            await db.execute(
                delete(Check).where(
                    Check.id.in_(
                        select(Check.id)
                        .where(
                            Check.created_at < cutoff,
                            or_(Check.batch_id.is_(None), Check.batch_id.not_in(select(Batch.id))),
                        )
                        .limit(batch_size * 10)
                    )
                )
            ),
        )
        await db.commit()
        if result.rowcount == 0:
            return checks, batches
        checks += result.rowcount
