"""HTTP client for the standalone detector service (apps/detector).

This is the "how we reach the detector" seam, kept separate from
services/checks.py so the policy layer (thresholds, abstention, verdicts)
doesn't have to know anything about HTTP. checks.py owns the *decision*;
this module owns *reaching the score*.
"""

from dataclasses import dataclass
from typing import Literal

import httpx

from config import DETECTOR_URL

MODEL_VERSION = "roberta-base-openai-detector-v0"

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


async def score_text(text: str) -> Score:
    response = await _client.post("/score", json={"text": text})
    response.raise_for_status()
    body = response.json()
    return Score(raw_score=body["raw_score"], truncated=body["truncated"])


async def health() -> Status:
    """Whether the detector can score right now.

    "loading" is worth telling apart from "unavailable": one resolves itself in
    a minute and the other needs somebody to go and look.
    """
    try:
        response = await _client.get("/health", timeout=HEALTH_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return "unavailable"

    if response.status_code == 200:
        return "ready"

    try:
        reported = response.json().get("status")
    except ValueError:
        return "unavailable"
    return "loading" if reported == "loading" else "unavailable"
