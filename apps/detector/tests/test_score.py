import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import baseline
from baseline import Score
from main import app

client = TestClient(app)

# What desklib + MELD reports once its bundle is loaded (the bundle isn't in the test environment).
CALIBRATED = {
    "model_version": "desklib-meld-ensemble-v1",
    "calibration_version": "desklib3.332-meld2.233-thr0.9458-v1",
    "threshold": 0.945775,
    "abstention_band": 0.005,
}


@pytest.fixture(autouse=True)
def _unloaded():
    """The status is a module global, so each test starts from a cold process."""
    baseline._set_status("loading")
    yield
    baseline._set_status("loading")


def test_health_is_503_until_the_model_is_loaded():
    """The API gates its own startup on this, so answering 200 early is what let
    the first real check pay the whole model load inside its 10s budget."""
    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "loading"


def test_health_is_200_with_the_calibration_of_the_running_model_once_ready():
    baseline._set_status("ready")
    with patch("main.calibration", return_value=CALIBRATED):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", **CALIBRATED}


def test_health_does_not_read_the_calibration_while_loading():
    """A bundle that fails its checks must still leave /health answering, so it reports only the name until ready."""
    with patch("main.calibration", side_effect=AssertionError("read while loading")):
        response = client.get("/health")

    assert response.json() == {"status": "loading", "model_version": baseline.MODEL_VERSION}


def test_a_failed_load_is_reported_as_failed_not_as_still_loading():
    """A load that is still running clears by itself and a broken one does not -
    the operator reading the badge needs to know which they are looking at."""
    baseline._set_status("failed")

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "failed"


def test_warm_up_runs_one_score_and_leaves_the_model_ready():
    with patch("desklib_meld.score", return_value=(0.5, False)) as scored:
        baseline.warm_up()

    scored.assert_called_once()
    assert baseline.status() == "ready"


def test_warm_up_survives_a_model_that_will_not_load():
    """A crashed warm-up must leave the service answering /health, not dead: the
    status is how anyone finds out what went wrong."""
    with patch("desklib_meld.score", side_effect=OSError("no model files")):
        baseline.warm_up()

    assert baseline.status() == "failed"
    assert client.get("/health").status_code == 503


def test_score_returns_the_score_with_the_threshold_and_band_fitted_for_the_running_model():
    with (
        patch("routes.score_text", return_value=Score(raw_score=0.97, truncated=True)),
        patch("routes.calibration", return_value=CALIBRATED),
    ):
        response = client.post("/score", json={"text": "some answer text"})

    assert response.status_code == 200
    assert response.json() == {"raw_score": 0.97, "truncated": True, **CALIBRATED}


def test_score_rejects_missing_text():
    response = client.post("/score", json={})
    assert response.status_code == 422


def test_score_text_is_safe_under_concurrent_threads():
    """routes.py hands every request to a worker thread, so two rows of a batch
    can enter score_text at once. The models' fast tokenizers are Rust objects
    that raise "RuntimeError: Already borrowed" when that happens - which
    surfaced as one row in twelve failing with a 503.

    The fake below is deliberately hostile in the same way: it refuses re-entry
    while another thread is inside it. Without the lock in score_text this fails.
    """
    import threading

    from baseline import score_text

    class _NotThreadSafe:
        """Stands in for desklib_meld.score: raises if two threads overlap."""

        def __init__(self):
            self._busy = False

        def __call__(self, text):
            if self._busy:
                raise RuntimeError("Already borrowed")
            self._busy = True
            time.sleep(0.005)
            self._busy = False
            return 0.9, False

    fake = _NotThreadSafe()
    errors: list[BaseException] = []

    def run():
        try:
            score_text("an answer long enough to score")
        except BaseException as exc:  # noqa: BLE001 - the assertion is the report
            errors.append(exc)

    with patch("desklib_meld.score", side_effect=fake):
        threads = [threading.Thread(target=run) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert errors == [], f"concurrent scoring raised: {errors!r}"
