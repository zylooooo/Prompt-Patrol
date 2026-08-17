import logging
import threading
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)

MODEL_VERSION = "roberta-base-openai-detector-v0"
MODEL_NAME = "openai-community/roberta-base-openai-detector"
MAX_TOKENS = 512

_AI_LABEL = "fake"


@dataclass(frozen=True)
class Score:
    raw_score: float
    truncated: bool


# The pipeline is a process-wide singleton holding a HuggingFace *fast*
# tokenizer - a Rust object that refuses concurrent use with "RuntimeError:
# Already borrowed". routes.py runs every request in a worker thread, so two
# requests arriving together hit exactly that, and one of them 500s.
#
# Nothing sent this service concurrent traffic until batch screening did, which
# is why it went unnoticed. Serialising is the right trade: a forward pass is
# CPU-bound and torch already parallelises inside it, so running two at once
# bought almost nothing even when it worked.
_lock = threading.Lock()


@lru_cache(maxsize=1)
def _pipeline():
    from transformers import pipeline

    logger.info("Loading baseline detector model %s", MODEL_NAME)
    return pipeline("text-classification", model=MODEL_NAME, top_k=None)


def score_text(text: str) -> Score:
    # Loading is inside the lock too: lru_cache does not make the miss atomic,
    # so a cold start under concurrency would otherwise build the model twice.
    with _lock:
        clf = _pipeline()
        tokenizer = clf.tokenizer
        token_count = len(tokenizer.encode(text, add_special_tokens=True))
        [scores] = clf([text], truncation=True, max_length=MAX_TOKENS)

    truncated = token_count > MAX_TOKENS
    ai_score = next(s["score"] for s in scores if s["label"].lower() == _AI_LABEL)
    return Score(raw_score=round(float(ai_score), 4), truncated=truncated)
