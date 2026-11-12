"""HTTP client for the standalone detector service (apps/detector).

This is the "how we reach the detector" seam, kept separate from
services/checks.py so the policy layer (thresholds, abstention, verdicts)
doesn't have to know anything about HTTP. checks.py owns the *decision*;
this module owns *reaching the score*.
"""

import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from config import DETECTOR_URL

# The detector reports its model, calibration, threshold and abstention band with every score and on /health
# (apps/detector/app/baseline.py calibration()), and that is what the API applies. These variables are only the
# fallback for a detector too old to report them (and the e2e stub): set them to match such a detector. A current
# detector needs none of them, and when one is set and disagrees, the detector wins and a warning is logged.
MODEL_VERSION = os.getenv("DETECTOR_MODEL_VERSION", "roberta-base-openai-detector-v0")

# None means uncalibrated
CALIBRATION_VERSION = os.getenv("DETECTOR_CALIBRATION_VERSION") or None

# What the detector reports about itself, in /score and /health bodies
REPORTED_FIELDS = ("model_version", "calibration_version", "threshold", "abstention_band")

# Short on purpose: this backs a status badge that polls, so a detector that has
# stopped answering should read as "unavailable" quickly rather than hold the
# request open. Scoring keeps its own, far longer budget.
HEALTH_TIMEOUT_SECONDS = 2.0

Status = Literal["ready", "loading", "unavailable"]

# httpx defaults to a 5s read timeout, shorter than the 10s budget
# services.checks_service enforces via asyncio.wait_for around this call. Set
# generously long here so that outer wait_for - not this client - is always
# what decides a slow detector is a timeout (504) rather than a spurious
# "unavailable" (503) from httpx cutting the request off first.
_client = httpx.AsyncClient(base_url=DETECTOR_URL, timeout=httpx.Timeout(30.0))


@dataclass(frozen=True)
class Score:
    raw_score: float
    truncated: bool
    # What the detector reported with the score. model_version None means a detector too old to report anything, so
    # the API's own settings apply; threshold/abstention_band None from a detector that does report means the model
    # is uncalibrated, so the API's uncalibrated defaults apply.
    model_version: str | None = None
    calibration_version: str | None = None
    threshold: float | None = None
    abstention_band: float | None = None


# The last calibration the detector reported, for the status badge and the capabilities endpoint, which have no score
# of their own to read it from. Empty until the detector first reports (then the environment's values are shown).
_reported: dict[str, Any] = {}


def _remember(body: dict) -> None:
    if body.get("model_version"):
        _reported.update({field: body.get(field) for field in REPORTED_FIELDS})


def reported_model_version() -> str:
    """The model the detector last said it is running, or DETECTOR_MODEL_VERSION if it hasn't said yet."""
    return _reported.get("model_version") or MODEL_VERSION


def reported_calibration_version() -> str | None:
    if _reported.get("model_version"):
        return _reported.get("calibration_version")
    return CALIBRATION_VERSION


async def score_text(text: str) -> Score:
    response = await _client.post("/score", json={"text": text})
    response.raise_for_status()
    body = response.json()
    _remember(body)
    return Score(
        raw_score=body["raw_score"],
        truncated=body["truncated"],
        model_version=body.get("model_version"),
        calibration_version=body.get("calibration_version"),
        threshold=body.get("threshold"),
        abstention_band=body.get("abstention_band"),
    )


async def health() -> Status:
    """Whether the detector can score right now.

    "loading" is worth telling apart from "unavailable": one resolves itself in
    a minute and the other needs somebody to go and look.
    """
    try:
        response = await _client.get("/health", timeout=HEALTH_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return "unavailable"

    try:
        body = response.json()
    except ValueError:
        body = None

    if response.status_code == 200:
        if isinstance(body, dict):
            _remember(body)
        return "ready"

    if not isinstance(body, dict):
        return "unavailable"
    return "loading" if body.get("status") == "loading" else "unavailable"
