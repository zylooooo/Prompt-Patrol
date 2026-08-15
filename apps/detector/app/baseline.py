import logging
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


@lru_cache(maxsize=1)
def _pipeline():
    from transformers import pipeline

    logger.info("Loading baseline detector model %s", MODEL_NAME)
    return pipeline("text-classification", model=MODEL_NAME, top_k=None)


def score_text(text: str) -> Score:
    clf = _pipeline()
    tokenizer = clf.tokenizer
    token_count = len(tokenizer.encode(text, add_special_tokens=True))
    truncated = token_count > MAX_TOKENS

    [scores] = clf([text], truncation=True, max_length=MAX_TOKENS)
    ai_score = next(s["score"] for s in scores if s["label"].lower() == _AI_LABEL)
    return Score(raw_score=round(float(ai_score), 4), truncated=truncated)
