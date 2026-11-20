"""The API applies the calibration the detector reports with each score, and falls back to its environment only for a
detector too old to report one."""

import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import services.checks_service as checks_service
import services.detector_client as detector_client
from services.detector_client import Score

DESKLIB_MELD = {
    "model_version": "desklib-meld-ensemble-v1",
    "calibration_version": "desklib3.332-meld2.233-thr0.9458-v1",
    "threshold": 0.945775,
    "abstention_band": 0.005,
}
LEVELS = {
    "lenient": {"target_fpr": 0.01, "threshold": 0.945775, "abstention_band": 0.005},
    "standard": {"target_fpr": 0.02, "threshold": 0.934459, "abstention_band": 0.006},
    "strict": {"target_fpr": 0.05, "threshold": 0.814079, "abstention_band": 0.0148},
}
# A detector with strictness_levels.json: its top-level pair is the standard level's
DESKLIB_MELD_LEVELS = {
    "model_version": "desklib-meld-ensemble-v1",
    "calibration_version": "desklib3.332-meld2.233-thr0.9458-v1+lenient1-standard2-strict5-logitband-v1",
    "threshold": 0.934459,
    "abstention_band": 0.006,
    "strictness_levels": LEVELS,
}
ROBERTA = {
    "model_version": "roberta-base-openai-detector-v0",
    "calibration_version": None,
    "threshold": None,
    "abstention_band": None,
}


def _response(method, path, status_code=200, **kwargs):
    return httpx.Response(request=httpx.Request(method, f"http://detector{path}"), status_code=status_code, **kwargs)


async def _scored(body):
    response = _response("POST", "/score", json=body)
    with patch.object(detector_client._client, "post", new=AsyncMock(return_value=response)):
        return await detector_client.score_text("an answer")


# --------------------------------------------------------------------------- reading the detector


@pytest.mark.asyncio
async def test_score_text_reads_the_calibration_the_detector_reports():
    score = await _scored({"raw_score": 0.97, "truncated": False, **DESKLIB_MELD})
    assert score == Score(raw_score=0.97, truncated=False, **DESKLIB_MELD)


@pytest.mark.asyncio
async def test_score_text_reads_the_per_level_settings_the_detector_reports():
    score = await _scored({"raw_score": 0.97, "truncated": False, **DESKLIB_MELD_LEVELS})
    assert score.strictness_levels == LEVELS


@pytest.mark.asyncio
async def test_score_text_still_reads_a_detector_that_reports_no_calibration():
    """An older detector image (or the e2e stub) sends only the score."""
    score = await _scored({"raw_score": 0.5, "truncated": True})
    assert score == Score(raw_score=0.5, truncated=True)
    assert score.model_version is None


@pytest.mark.asyncio
async def test_the_badge_names_the_model_the_detector_reports_once_it_has_reported():
    assert detector_client.reported_model_version() == detector_client.MODEL_VERSION
    response = _response("GET", "/health", json={"status": "ready", **DESKLIB_MELD})
    with patch.object(detector_client._client, "get", new=AsyncMock(return_value=response)):
        assert await detector_client.health() == "ready"
    assert detector_client.reported_model_version() == "desklib-meld-ensemble-v1"
    assert detector_client.reported_calibration_version() == "desklib3.332-meld2.233-thr0.9458-v1"


@pytest.mark.asyncio
async def test_a_loading_detector_does_not_change_what_is_reported():
    response = _response("GET", "/health", status_code=503, json={"status": "loading", "model_version": "other"})
    with patch.object(detector_client._client, "get", new=AsyncMock(return_value=response)):
        assert await detector_client.health() == "loading"
    assert detector_client.reported_model_version() == detector_client.MODEL_VERSION


def test_capabilities_name_the_reported_model_and_calibration():
    detector_client._remember({"status": "ready", **DESKLIB_MELD})
    caps = checks_service.detector_capabilities()
    assert caps["model_version"] == "desklib-meld-ensemble-v1"
    assert caps["calibration_version"] == "desklib3.332-meld2.233-thr0.9458-v1"


# --------------------------------------------------------------------------- choosing the settings


@pytest.mark.parametrize("strictness", ["lenient", "standard", "strict"])
def test_a_calibrated_detector_s_threshold_and_band_are_applied_at_every_strictness(strictness):
    applied = checks_service._settings_for(Score(0.9, False, **DESKLIB_MELD), strictness)
    assert applied == checks_service.AppliedSettings(
        model_version="desklib-meld-ensemble-v1",
        calibration_version="desklib3.332-meld2.233-thr0.9458-v1",
        threshold=0.945775,
        abstention_band=0.005,
        target_fpr=checks_service.TARGET_FPR[strictness],
    )


@pytest.mark.parametrize("strictness", ["lenient", "standard", "strict"])
def test_each_strictness_gets_the_pair_the_detector_fitted_for_it(strictness):
    applied = checks_service._settings_for(Score(0.9, False, **DESKLIB_MELD_LEVELS), strictness)
    fitted = LEVELS[strictness]
    assert applied == checks_service.AppliedSettings(
        model_version="desklib-meld-ensemble-v1",
        calibration_version="desklib3.332-meld2.233-thr0.9458-v1+lenient1-standard2-strict5-logitband-v1",
        threshold=fitted["threshold"],
        abstention_band=fitted["abstention_band"],
        target_fpr=fitted["target_fpr"],
    )


def test_a_score_between_two_levels_thresholds_is_flagged_only_at_the_stricter_one():
    """0.9 is above strict's 0.814079 + 0.0148 but below standard's 0.934459 - 0.006 and lenient's 0.945775 - 0.005:
    a stricter detector flags it, the others clear it."""
    verdicts = {}
    for level in ("strict", "standard", "lenient"):
        applied = checks_service._settings_for(Score(0.9, False, **DESKLIB_MELD_LEVELS), level)
        verdicts[level] = checks_service._decide(0.9, applied.threshold, 20, applied.abstention_band)[0]
    assert verdicts == {"strict": "ai_generated", "standard": "human_written", "lenient": "human_written"}


def test_per_level_settings_are_not_compared_with_the_single_environment_threshold(monkeypatch, caplog):
    monkeypatch.setattr(checks_service, "_ENV_THRESHOLD", "0.945775")
    with caplog.at_level(logging.WARNING, logger=checks_service.logger.name):
        checks_service._settings_for(Score(0.9, False, **DESKLIB_MELD_LEVELS), "lenient")
    assert not [r for r in caplog.records if "threshold=" in r.getMessage()]


def test_capabilities_report_the_target_fpr_the_detector_fitted_each_level_to(monkeypatch):
    monkeypatch.setattr(checks_service, "STRICTNESS_ENABLED", True)
    detector_client._remember({"status": "ready", **DESKLIB_MELD_LEVELS})
    caps = checks_service.detector_capabilities()
    assert caps["strictness_levels"] == [
        {"level": "lenient", "target_fpr": 0.01, "threshold": 0.945775},
        {"level": "standard", "target_fpr": 0.02, "threshold": 0.934459},
        {"level": "strict", "target_fpr": 0.05, "threshold": 0.814079},
    ]


@pytest.mark.parametrize("strictness", ["lenient", "standard", "strict"])
def test_capabilities_threshold_is_the_one_a_check_at_that_level_would_use(strictness, monkeypatch):
    monkeypatch.setattr(checks_service, "STRICTNESS_ENABLED", True)
    for body in (DESKLIB_MELD_LEVELS, DESKLIB_MELD, ROBERTA):
        detector_client._reported.clear()
        detector_client._remember({"status": "ready", **body})
        offered = {
            row["level"]: row["threshold"] for row in checks_service.detector_capabilities()["strictness_levels"]
        }
        applied = checks_service._settings_for(Score(0.9, False, **body), strictness)
        assert offered[strictness] == applied.threshold, body["model_version"]


def test_capabilities_show_no_threshold_before_anything_names_the_model(monkeypatch):
    monkeypatch.setattr(detector_client, "MODEL_VERSION", None)
    monkeypatch.setattr(detector_client, "_reported", {})
    levels = checks_service.detector_capabilities()["strictness_levels"]
    assert all(row["threshold"] is None for row in levels)


@pytest.mark.parametrize("strictness", ["lenient", "standard", "strict"])
def test_an_uncalibrated_detector_gets_the_uncalibrated_defaults_not_the_environment(strictness, monkeypatch):
    """A threshold set for some other model must not be applied to the roberta baseline's scores."""
    monkeypatch.setattr(checks_service, "_ENV_THRESHOLD", "0.9608")
    applied = checks_service._settings_for(Score(0.9, False, **ROBERTA), strictness)
    assert applied.threshold == checks_service.UNCALIBRATED_THRESHOLDS[strictness]
    assert applied.abstention_band == checks_service.UNCALIBRATED_ABSTENTION_BAND
    assert applied.calibration_version is None


def test_a_detector_that_reports_nothing_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setattr(checks_service, "THRESHOLDS", dict.fromkeys(checks_service.THRESHOLDS, 0.9608))
    monkeypatch.setattr(checks_service, "ABSTENTION_BAND", 0.01)
    monkeypatch.setattr(checks_service, "MODEL_VERSION", "desklib-academic-lora-v1")
    monkeypatch.setattr(checks_service, "CALIBRATION_VERSION", "desklib-temp1.944-v1")
    applied = checks_service._settings_for(Score(0.9, False), "standard")
    assert applied == checks_service.AppliedSettings(
        "desklib-academic-lora-v1", "desklib-temp1.944-v1", 0.9608, 0.01, checks_service.TARGET_FPR["standard"]
    )


def test_nothing_is_reported_before_the_detector_says_which_model_it_runs(monkeypatch):
    """No guessed default: a loading detector must not be shown as some other model."""
    monkeypatch.setattr(detector_client, "MODEL_VERSION", None)
    monkeypatch.setattr(detector_client, "_reported", {})
    assert detector_client.reported_model_version() is None
    assert checks_service.detector_capabilities()["model_version"] is None


def test_a_check_from_a_detector_that_reports_nothing_still_names_a_model(monkeypatch):
    monkeypatch.setattr(checks_service, "MODEL_VERSION", None)
    applied = checks_service._settings_for(Score(0.9, False), "standard")
    assert applied.model_version == detector_client.UNREPORTED_MODEL_VERSION


def test_a_stale_environment_threshold_loses_to_the_detector_and_is_logged_once(monkeypatch, caplog):
    """The failure this whole change exists for: the model was updated, the API's variable wasn't."""
    monkeypatch.setattr(checks_service, "_ENV_THRESHOLD", "0.9608")
    with caplog.at_level(logging.WARNING, logger=checks_service.logger.name):
        first = checks_service._settings_for(Score(0.9, False, **DESKLIB_MELD), "standard")
        checks_service._settings_for(Score(0.9, False, **DESKLIB_MELD), "standard")
    assert first.threshold == 0.945775
    warnings = [r for r in caplog.records if "threshold=0.945775" in r.getMessage()]
    assert len(warnings) == 1
    assert "0.9608" in warnings[0].getMessage()


def test_a_matching_environment_is_not_reported_as_a_mismatch(monkeypatch, caplog):
    monkeypatch.setattr(checks_service, "_ENV_THRESHOLD", "0.945775")
    monkeypatch.setattr(checks_service, "_ENV_BAND", "0.005")
    monkeypatch.setenv("DETECTOR_MODEL_VERSION", "desklib-meld-ensemble-v1")
    monkeypatch.setenv("DETECTOR_CALIBRATION_VERSION", "desklib3.332-meld2.233-thr0.9458-v1")
    with caplog.at_level(logging.WARNING, logger=checks_service.logger.name):
        checks_service._settings_for(Score(0.9, False, **DESKLIB_MELD), "standard")
    assert not caplog.records


# --------------------------------------------------------------------------- the verdict


@pytest.mark.parametrize(
    ("raw_score", "verdict"),
    [(0.96, "ai_generated"), (0.948, "uncertain"), (0.944, "uncertain"), (0.93, "human_written")],
)
def test_the_reported_band_decides_what_is_uncertain(raw_score, verdict):
    """With the old default band of 0.08 every one of these would be uncertain."""
    assert checks_service._decide(raw_score, 0.945775, 20, 0.005)[0] == verdict
