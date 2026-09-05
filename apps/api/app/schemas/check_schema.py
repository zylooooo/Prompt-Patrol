import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from models import AbstainReasonEnum, Check, StrictnessEnum, VerdictEnum


class DetectorInfo(BaseModel):
    """The detector's settings as they were when this check ran. Re-nested from
    flat columns because that is the shape `apps/web/src/types.ts` reads."""

    model_version: str
    calibration_version: str | None
    strictness_applied: StrictnessEnum
    threshold_applied: float
    target_fpr: float | None
    used_question_text: bool


class CheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    check_id: uuid.UUID
    actor_id: uuid.UUID
    batch_id: uuid.UUID | None
    batch_file_name: str | None
    external_ref: str | None
    verdict: VerdictEnum
    raw_score: float
    confidence: float | None
    abstain_reason: AbstainReasonEnum | None
    truncated: bool
    detector: DetectorInfo
    answer_text: str | None
    question_text: str | None
    created_at: datetime
    latency_ms: int | None

    @classmethod
    def of(cls, check: Check) -> "CheckResponse":
        """One place where a stored row becomes the wire shape. `check_id` and
        the nested `detector` block are the two things a plain
        `model_validate` cannot do from these columns."""
        return cls(
            check_id=check.id,
            actor_id=check.actor_id,
            batch_id=check.batch_id,
            batch_file_name=check.batch_file_name,
            external_ref=check.external_ref,
            verdict=check.verdict,
            raw_score=check.raw_score,
            confidence=check.confidence,
            abstain_reason=check.abstain_reason,
            truncated=check.truncated,
            detector=DetectorInfo(
                model_version=check.model_version,
                calibration_version=check.calibration_version,
                strictness_applied=check.strictness_applied,
                threshold_applied=check.threshold_applied,
                target_fpr=check.target_fpr,
                used_question_text=check.used_question_text,
            ),
            answer_text=check.answer_text,
            question_text=check.question_text,
            created_at=check.created_at,
            latency_ms=check.latency_ms,
        )


class CheckSummary(BaseModel):
    """History table row."""

    model_config = ConfigDict(from_attributes=True)

    check_id: uuid.UUID
    actor_id: uuid.UUID
    batch_id: uuid.UUID | None
    batch_file_name: str | None
    external_ref: str | None
    verdict: VerdictEnum
    raw_score: float
    confidence: float | None
    strictness_applied: StrictnessEnum
    model_version: str
    answer_text: str | None
    created_at: datetime

    @classmethod
    def of(cls, check: Check) -> "CheckSummary":
        return cls(
            check_id=check.id,
            actor_id=check.actor_id,
            batch_id=check.batch_id,
            batch_file_name=check.batch_file_name,
            external_ref=check.external_ref,
            verdict=check.verdict,
            raw_score=check.raw_score,
            confidence=check.confidence,
            strictness_applied=check.strictness_applied,
            model_version=check.model_version,
            answer_text=check.answer_text,
            created_at=check.created_at,
        )


class CheckListResponse(BaseModel):
    items: list[CheckSummary]
    next_cursor: str | None = None
