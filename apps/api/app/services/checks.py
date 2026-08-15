import asyncio
import time
import uuid
from datetime import UTC, datetime

from services.detector_client import MODEL_VERSION, score_text

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


class DetectorTimeoutError(Exception):
    """The detector call exceeded DETECTOR_TIMEOUT_SECONDS."""


class DetectorUnavailableError(Exception):
    """The detector call failed for any other reason."""


def _decide(raw_score: float, threshold: float, word_count: int) -> tuple[str, str | None]:
    if word_count < MIN_ANSWER_WORDS:
        return "uncertain", "answer_too_short"
    if abs(raw_score - threshold) <= ABSTENTION_BAND:
        return "uncertain", "score_in_abstention_band"
    return ("ai_generated" if raw_score > threshold else "human_written"), None


async def create_check(
    *,
    actor_id: uuid.UUID,
    answer_text: str,
    question_text: str | None,
    external_ref: str | None,
    strictness: str,
    retain_answer: bool,
) -> dict:
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

    return {
        "check_id": uuid.uuid4(),
        "actor_id": actor_id,
        "batch_id": None,
        "external_ref": external_ref,
        "verdict": verdict,
        "raw_score": result.raw_score,
        "confidence": None,
        "abstain_reason": abstain_reason,
        "truncated": result.truncated,
        "detector": {
            "model_version": MODEL_VERSION,
            "calibration_version": None,
            "strictness_applied": strictness,
            "threshold_applied": threshold,
            "target_fpr": TARGET_FPR[strictness],
            "used_question_text": False,
        },
        "answer_text": answer_text if retain_answer else None,
        "question_text": question_text,
        "explanation": None,
        "spans": None,
        "created_at": datetime.now(UTC),
        "latency_ms": latency_ms,
    }
