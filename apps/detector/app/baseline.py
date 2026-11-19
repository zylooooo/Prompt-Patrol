import logging
import threading
from dataclasses import dataclass
from typing import Literal

import desklib_meld

logger = logging.getLogger(__name__)

# The served model: desklib + MELD (desklib_meld.py, docs/desklib-meld-release.md). This module keeps what is not
# model-specific: the scoring lock, the load status and the warm-up.
MODEL_VERSION = desklib_meld.MODEL_VERSION

# "loading" until warm_up finishes, then "ready" or "failed" for good.
Status = Literal["loading", "ready", "failed"]


@dataclass(frozen=True)
class Score:
    raw_score: float
    truncated: bool


# The models are process-wide singletons holding HuggingFace *fast* tokenizers -
# Rust objects that refuse concurrent use with "RuntimeError: Already borrowed".
# routes.py runs every request in a worker thread, so two requests arriving
# together hit exactly that, and one of them 500s.
#
# Nothing sent this service concurrent traffic until batch screening did, which
# is why it went unnoticed. Serialising is the right trade: a forward pass is
# CPU-bound and torch already parallelises inside it, so running two at once
# bought almost nothing even when it worked.
_lock = threading.Lock()

_status: Status = "loading"
_status_lock = threading.Lock()


def calibration() -> dict:
    """The running model and the decision settings fitted for it: model_version, calibration_version, threshold and
    abstention_band. Sent with every score so the API applies what was fitted for this model, not a hand-copied value
    that can go stale."""
    return desklib_meld.calibration()


def status() -> Status:
    """Whether the model is loaded yet, for /health to report."""
    with _status_lock:
        return _status


def _set_status(value: Status) -> None:
    global _status
    with _status_lock:
        _status = value


def warm_up() -> None:
    """Load the model up front so no request has to pay for it."""
    # A real forward pass, not just the constructor: the first call is what
    # materialises the weights and builds the tokenizer, so "ready" would
    # otherwise still leave several seconds of work for the first caller.
    try:
        with _lock:
            desklib_meld.score("warm up")
        # A strictness_levels.json fitted for another bundle fails here, at start-up, not on every score
        calibration()
    except Exception:
        logger.exception("Detector model failed to load")
        _set_status("failed")
        return

    _set_status("ready")
    logger.info("Detector model ready")


def score_text(text: str) -> Score:
    # The models load inside the lock too: lru_cache does not make the miss atomic, so a cold start under concurrency
    # would otherwise build them twice.
    with _lock:
        probability, truncated = desklib_meld.score(text)
    return Score(raw_score=probability, truncated=truncated)
