import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import torch

import baseline
import desklib
import ensemble

SHIPPED_SETTINGS = Path(__file__).parent.parent / "model" / "ensemble.json"


def config(**overrides):
    values = {
        "model_version": ensemble.MODEL_VERSION,
        "weight_radar": 0.5,
        "desklib_temperature": desklib.TEMPERATURE,
        "desklib_model_version": desklib.MODEL_VERSION,
        "radar_model": "TrustSafeAI/RADAR-Vicuna-7B",
        "radar_revision": "4ff1f23a69a36aa1df47b0933be6279f1b896c9b",
        "radar_temperature": 1.5,
        "max_tokens": ensemble.MAX_TOKENS,
    }
    return values | overrides


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


class FakeDesklib:
    def __init__(self, logit):
        self.logit = logit

    def __call__(self, input_ids, attention_mask):
        return {"logits": torch.tensor([[self.logit]])}


class FakeRadar:
    """RADAR's two outputs, [AI, human]."""

    def __init__(self, ai, human):
        self.out = torch.tensor([[ai, human]])

    def __call__(self, input_ids, attention_mask):
        return SimpleNamespace(logits=self.out)


def scored(text, d_logit=0.0, r_ai=0.0, r_human=0.0, settings=None):
    d_tok, r_tok = FakeTokenizer(), FakeTokenizer()
    with (
        patch("ensemble.settings", return_value=settings or config()),
        patch("desklib.load", return_value=(d_tok, FakeDesklib(d_logit))),
        patch("ensemble.load_radar", return_value=(r_tok, FakeRadar(r_ai, r_human))),
    ):
        return ensemble.score(text), d_tok, r_tok


def test_combine_averages_each_logit_over_its_own_temperature():
    cfg = config(weight_radar=0.5, desklib_temperature=2.0, radar_temperature=4.0)
    z = 0.5 * 6.0 / 2.0 + 0.5 * -8.0 / 4.0
    assert ensemble.combine(6.0, -8.0, cfg) == pytest.approx(1 / (1 + math.exp(-z)))


def test_combine_with_all_weight_on_desklib_is_desklibs_own_probability():
    cfg = config(weight_radar=0.0)
    assert ensemble.combine(3.0, 100.0, cfg) == pytest.approx(desklib.calibrated_probability(3.0))


def test_score_cleans_the_text_once_for_both_models():
    """Both models were calibrated on cleaned text, so both must be fed cleaned text."""
    _, d_tok, r_tok = scored("**Ans:** a stack is LIFO &amp; fast")
    assert d_tok.seen == ["a stack is LIFO & fast"]
    assert r_tok.seen == ["a stack is LIFO & fast"]


def test_score_reads_radar_as_ai_minus_human():
    cfg = config(weight_radar=1.0, radar_temperature=1.0)
    (probability, _), _, _ = scored("an answer about queues", r_ai=2.0, r_human=-1.0, settings=cfg)
    assert probability == round(desklib.calibrated_probability(3.0, 1.0), 6)


def test_score_reports_truncation_when_either_model_cuts_the_text():
    long_answer = " ".join(["word"] * (ensemble.MAX_TOKENS + 5))
    (_, truncated), _, _ = scored(long_answer)
    assert truncated is True
    (_, truncated), _, _ = scored("a short answer")
    assert truncated is False


def test_settings_refuse_a_calibration_for_a_different_desklib(tmp_path, monkeypatch):
    path = tmp_path / "ensemble.json"
    path.write_text(json.dumps(config(desklib_temperature=desklib.TEMPERATURE + 1)))
    monkeypatch.setattr(ensemble, "SETTINGS_PATH", path)
    ensemble.settings.cache_clear()
    with pytest.raises(ValueError, match="rerun calibrate_ensemble.py"):
        ensemble.settings()
    ensemble.settings.cache_clear()


def test_settings_refuse_a_file_with_missing_keys(tmp_path, monkeypatch):
    path = tmp_path / "ensemble.json"
    values = config()
    del values["radar_temperature"]
    path.write_text(json.dumps(values))
    monkeypatch.setattr(ensemble, "SETTINGS_PATH", path)
    ensemble.settings.cache_clear()
    with pytest.raises(ValueError, match="missing"):
        ensemble.settings()
    ensemble.settings.cache_clear()


def test_settings_fail_loudly_when_the_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ensemble, "SETTINGS_PATH", tmp_path / "nowhere.json")
    ensemble.settings.cache_clear()
    with pytest.raises(FileNotFoundError):
        ensemble.settings()
    ensemble.settings.cache_clear()


def test_the_shipped_settings_match_the_code_and_the_live_desklib(monkeypatch):
    monkeypatch.setattr(ensemble, "SETTINGS_PATH", SHIPPED_SETTINGS)
    ensemble.settings.cache_clear()
    values = ensemble.settings()
    ensemble.settings.cache_clear()
    assert 0 < values["threshold"] < 1
    assert values["target_fpr"] == 0.01


def test_load_radar_fails_loudly_when_the_adapter_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ensemble, "RADAR_ADAPTER_DIR", tmp_path)
    ensemble.load_radar.cache_clear()
    with pytest.raises(FileNotFoundError, match="RADAR LoRA adapter"):
        ensemble.load_radar()
    ensemble.load_radar.cache_clear()


def test_the_ensemble_backend_is_used_when_selected(monkeypatch):
    monkeypatch.setattr(baseline, "BACKEND", "ensemble")
    monkeypatch.setattr(baseline, "ensemble", ensemble, raising=False)
    with patch("ensemble.score", return_value=(0.81, False)) as fake:
        result = baseline.score_text("an answer")
    fake.assert_called_once_with("an answer")
    assert result == baseline.Score(raw_score=0.81, truncated=False)


def test_warm_up_runs_one_ensemble_score_when_selected(monkeypatch):
    monkeypatch.setattr(baseline, "BACKEND", "ensemble")
    monkeypatch.setattr(baseline, "ensemble", ensemble, raising=False)
    with patch("ensemble.score", return_value=(0.5, False)) as fake:
        baseline.warm_up()
    fake.assert_called_once()
    assert baseline.status() == "ready"
