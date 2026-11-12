import json
import math
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import torch

import baseline
import desklib_meld

TEMPS = {"desklib": 3.33237, "meld": 2.232665}


def config(**overrides):
    values = {
        "model_version": desklib_meld.MODEL_VERSION,
        "calibration_version": "desklib3.332-meld2.233-thr0.9458-v1",
        "threshold": 0.945775,
        "weight_meld": 0.5,
        "cleaning_version": desklib_meld.CLEANING_VERSION,
        "desklib": {
            "base_model": "desklib/ai-text-detector-academic-v1.01",
            "base_revision": "fe9b4da50ee2cca5c877d607640681609170e363",
            "adapter": "desklib-lora-adapter",
            "temperature": TEMPS["desklib"],
            "max_tokens": desklib_meld.DESKLIB_MAX_TOKENS,
        },
        "meld": {
            "base_revision": "8990324abd92e1fa17072f6887ea1e5c1cef5abc",
            "adapter": "meld-soup-adapter",
            "head": "meld-soup-head.safetensors",
            "temperature": TEMPS["meld"],
        },
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


class FakeMeld:
    """MELD's Scorer: a document score, and its own flagged/threshold that the backend must ignore."""

    def __init__(self, score, truncated=False):
        self.result = {"score": score, "flagged": True, "threshold_fpr_0.01": 2.0, "truncated": truncated}
        self.seen = []

    def score(self, text):
        self.seen.append(text)
        return self.result


def scored(text, d_logit=0.0, m_score=0.0, m_truncated=False, settings=None):
    d_tok, meld = FakeTokenizer(), FakeMeld(m_score, m_truncated)
    with (
        patch("desklib_meld.settings", return_value=settings or config()),
        patch("desklib_meld.load_desklib", return_value=(d_tok, FakeDesklib(d_logit))),
        patch("desklib_meld.load_meld", return_value=meld),
    ):
        return desklib_meld.score(text), d_tok, meld


def write_settings(tmp_path, monkeypatch, values):
    (tmp_path / "desklib-meld.json").write_text(json.dumps(values))
    monkeypatch.setattr(desklib_meld, "SETTINGS_PATH", tmp_path / "desklib-meld.json")
    desklib_meld.settings.cache_clear()


@pytest.fixture(autouse=True)
def fresh_caches():
    desklib_meld.settings.cache_clear()
    yield
    desklib_meld.settings.cache_clear()


# --------------------------------------------------------------------------- combining


def test_combine_averages_the_log_odds_each_over_its_own_temperature():
    cfg = config()
    z = 0.5 * 6.0 / TEMPS["desklib"] + 0.5 * -3.0 / TEMPS["meld"]
    assert desklib_meld.combine(6.0, -3.0, cfg) == pytest.approx(1 / (1 + math.exp(-z)))


def test_combine_is_not_the_average_of_the_two_probabilities():
    cfg = config()
    p_d = 1 / (1 + math.exp(-8.0 / TEMPS["desklib"]))
    p_m = 1 / (1 + math.exp(2.0 / TEMPS["meld"]))
    assert desklib_meld.combine(8.0, -2.0, cfg) != pytest.approx((p_d + p_m) / 2, abs=1e-3)


def test_combine_with_all_weight_on_meld_is_melds_own_calibrated_probability():
    cfg = config(weight_meld=1.0)
    assert desklib_meld.combine(50.0, 4.0, cfg) == pytest.approx(1 / (1 + math.exp(-4.0 / TEMPS["meld"])))


# --------------------------------------------------------------------------- scoring


def test_score_cleans_the_text_once_and_gives_both_models_the_same_text():
    (_, _), d_tok, meld = scored("  An   answer with  odd   spacing  ")
    assert len(d_tok.seen) == 1 and len(meld.seen) == 1
    assert d_tok.seen[0] == meld.seen[0] == desklib_meld.clean_text("  An   answer with  odd   spacing  ")


def test_score_ignores_melds_own_flag_and_threshold():
    (probability, _), _, _ = scored("an answer", d_logit=-20.0, m_score=-20.0)
    assert probability < 0.01


def test_score_returns_the_combined_probability_rounded():
    (probability, _), _, _ = scored("an answer", d_logit=4.0, m_score=3.0)
    assert probability == round(desklib_meld.combine(4.0, 3.0, config()), 6)


def test_score_reports_truncation_when_desklib_cuts_the_text():
    (_, truncated), _, _ = scored("word " * (desklib_meld.DESKLIB_MAX_TOKENS + 1))
    assert truncated


def test_score_reports_truncation_when_meld_cuts_the_text():
    (_, truncated), _, _ = scored("a short answer", m_truncated=True)
    assert truncated


def test_score_does_not_report_truncation_for_a_short_answer():
    (_, truncated), _, _ = scored("a short answer")
    assert not truncated


# --------------------------------------------------------------------------- settings


def test_settings_fail_loudly_when_the_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(desklib_meld, "SETTINGS_PATH", tmp_path / "desklib-meld.json")
    with pytest.raises(FileNotFoundError, match="fetch the bundle"):
        desklib_meld.settings()


def test_settings_refuse_a_file_with_missing_keys(tmp_path, monkeypatch):
    values = config()
    del values["weight_meld"]
    del values["meld"]["temperature"]
    write_settings(tmp_path, monkeypatch, values)
    with pytest.raises(ValueError, match=r"weight_meld.*meld\.temperature"):
        desklib_meld.settings()


def test_settings_refuse_a_different_model_version(tmp_path, monkeypatch):
    write_settings(tmp_path, monkeypatch, config(model_version="desklib-meld-ensemble-v2"))
    with pytest.raises(ValueError, match="this code is desklib-meld-ensemble-v1"):
        desklib_meld.settings()


def test_settings_refuse_a_different_cleaning_version(tmp_path, monkeypatch):
    write_settings(tmp_path, monkeypatch, config(cleaning_version="clean_v1"))
    with pytest.raises(ValueError, match="clean_v1"):
        desklib_meld.settings()


def test_settings_refuse_a_different_desklib_cut(tmp_path, monkeypatch):
    values = config()
    values["desklib"]["max_tokens"] = 512
    write_settings(tmp_path, monkeypatch, values)
    with pytest.raises(ValueError, match="512"):
        desklib_meld.settings()


def test_meld_base_of_a_different_revision_is_refused(tmp_path, monkeypatch):
    (tmp_path / "REVISION").write_text("ddfc9c789b8c8d0f92d3774265316d418c96dc67\n")
    monkeypatch.setattr(desklib_meld, "MELD_BASE_DIR", tmp_path)
    with pytest.raises(ValueError, match="MELD@ddfc9c789b8c"):
        desklib_meld._check_meld_revision(config())


def test_meld_base_without_a_revision_marker_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(desklib_meld, "MELD_BASE_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="prepare_desklib_meld_base.sh"):
        desklib_meld._check_meld_revision(config())


def test_load_desklib_fails_loudly_when_the_adapter_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(desklib_meld, "BUNDLE_DIR", tmp_path)
    desklib_meld.load_desklib.cache_clear()
    with patch("desklib_meld.settings", return_value=config()), pytest.raises(FileNotFoundError, match="adapter"):
        desklib_meld.load_desklib()
    desklib_meld.load_desklib.cache_clear()


# --------------------------------------------------------------------------- wiring


def test_the_desklib_meld_backend_is_used_when_selected(monkeypatch):
    monkeypatch.setattr(baseline, "BACKEND", "desklib-meld")
    monkeypatch.setattr(baseline, "desklib_meld", desklib_meld, raising=False)
    with patch("desklib_meld.score", return_value=(0.97, True)) as fake:
        result = baseline.score_text("an answer")
    fake.assert_called_once_with("an answer")
    assert result == baseline.Score(raw_score=0.97, truncated=True)


def test_warm_up_runs_one_desklib_meld_score_when_selected(monkeypatch):
    monkeypatch.setattr(baseline, "BACKEND", "desklib-meld")
    monkeypatch.setattr(baseline, "desklib_meld", desklib_meld, raising=False)
    with patch("desklib_meld.score", return_value=(0.5, False)) as fake:
        baseline.warm_up()
    fake.assert_called_once()
    assert baseline.status() == "ready"


# --------------------------------------------------------------------------- the real models

GOLDEN = desklib_meld.BUNDLE_DIR / "golden.json"
HAVE_MODELS = GOLDEN.exists() and (desklib_meld.MELD_BASE_DIR / "meld.py").exists()


@pytest.mark.skipif(
    not HAVE_MODELS or os.getenv("HF_HUB_OFFLINE") != "1",
    reason="needs the bundle and MELD's base model (the desklib-meld image), run with HF_HUB_OFFLINE=1",
)
def test_the_shipped_models_reproduce_every_golden_probability():
    """The release's 23 answers, scored through this backend, against what release_desklib_meld.py measured."""
    golden = json.loads(Path(GOLDEN).read_text())
    assert golden["threshold"] == desklib_meld.settings()["threshold"]
    tolerance = golden["tolerance_probability"]
    misses = []
    for answer in golden["answers"]:
        probability, _ = desklib_meld.score(answer["text"])
        if abs(probability - answer["probability"]) > tolerance:
            misses.append((answer["answer_id"], answer["probability"], probability))
        assert (probability > golden["threshold"]) == answer["above_threshold"] or abs(
            probability - golden["threshold"]
        ) <= tolerance
    assert not misses, f"{len(misses)} of {len(golden['answers'])} off by more than {tolerance}: {misses[:5]}"
