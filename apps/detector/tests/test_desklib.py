import math
from unittest.mock import patch

import pytest
import torch

import baseline
import desklib


class FakeTokenizer:
    """Records what it is asked to encode, and counts one token per word."""

    def __init__(self):
        self.seen = []

    def encode(self, text, add_special_tokens=True):
        return text.split()

    def __call__(self, text, truncation=True, max_length=256, return_tensors="pt"):
        self.seen.append(text)
        n = min(len(text.split()), max_length)
        return {"input_ids": torch.ones(1, n, dtype=torch.long), "attention_mask": torch.ones(1, n, dtype=torch.long)}


class FakeModel:
    def __init__(self, logit):
        self.logit = logit

    def __call__(self, input_ids, attention_mask):
        return {"logits": torch.tensor([[self.logit]])}


def test_calibrated_probability_is_a_sigmoid_of_the_logit_over_the_temperature():
    assert desklib.calibrated_probability(0.0, 2.0) == 0.5
    assert desklib.calibrated_probability(4.0, 2.0) == pytest.approx(1 / (1 + math.exp(-2.0)))
    assert desklib.calibrated_probability(-4.0, 2.0) == pytest.approx(1 / (1 + math.exp(2.0)))


def test_calibrated_probability_survives_logits_that_would_overflow_exp():
    assert desklib.calibrated_probability(-5000.0, 1.0) == 0.0
    assert desklib.calibrated_probability(5000.0, 1.0) == 1.0


def test_score_cleans_the_text_before_the_model_sees_it():
    """Training answers were cleaned, so the model must be fed cleaned text."""
    tokenizer = FakeTokenizer()
    with patch("desklib.load", return_value=(tokenizer, FakeModel(0.0))):
        desklib.score("**Ans:** a stack is LIFO &amp; fast")

    assert tokenizer.seen == ["a stack is LIFO & fast"]


def test_score_applies_the_temperature_to_the_models_logit():
    with patch("desklib.load", return_value=(FakeTokenizer(), FakeModel(3.0))):
        probability, truncated = desklib.score("a short answer about stacks")

    assert probability == round(desklib.calibrated_probability(3.0), 6)
    assert truncated is False


def test_score_reports_truncation_past_the_training_length():
    long_answer = " ".join(["word"] * (desklib.MAX_TOKENS + 5))
    with patch("desklib.load", return_value=(FakeTokenizer(), FakeModel(0.0))):
        _, truncated = desklib.score(long_answer)

    assert truncated is True


def test_load_fails_loudly_when_the_adapter_is_missing(tmp_path):
    desklib.load.cache_clear()
    with patch("desklib.ADAPTER_DIR", tmp_path / "missing"), pytest.raises(FileNotFoundError):
        desklib.load()
    desklib.load.cache_clear()


def test_the_desklib_backend_is_used_when_selected(monkeypatch):
    monkeypatch.setattr(baseline, "BACKEND", "desklib")
    monkeypatch.setattr(baseline, "desklib", desklib, raising=False)

    with patch("desklib.score", return_value=(0.97, False)):
        result = baseline.score_text("some answer")

    assert result == baseline.Score(raw_score=0.97, truncated=False)


def test_warm_up_runs_one_desklib_score_when_selected(monkeypatch):
    monkeypatch.setattr(baseline, "BACKEND", "desklib")
    monkeypatch.setattr(baseline, "desklib", desklib, raising=False)

    with patch("desklib.score", return_value=(0.5, False)) as scored:
        baseline.warm_up()

    scored.assert_called_once_with("warm up")
    assert baseline.status() == "ready"
    baseline._set_status("loading")
