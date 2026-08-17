import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from baseline import Score
from main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_score_happy_path():
    with patch("routes.score_text", return_value=Score(raw_score=0.87, truncated=False)):
        response = client.post("/score", json={"text": "some answer text"})

    assert response.status_code == 200
    assert response.json() == {"raw_score": 0.87, "truncated": False}


def test_score_rejects_missing_text():
    response = client.post("/score", json={})
    assert response.status_code == 422


def test_score_text_is_safe_under_concurrent_threads():
    """routes.py hands every request to a worker thread, so two rows of a batch
    can enter score_text at once. The pipeline's fast tokenizer is a Rust object
    that raises "RuntimeError: Already borrowed" when that happens - which
    surfaced as one row in twelve failing with a 503.

    The fake below is deliberately hostile in the same way: it refuses re-entry
    while another thread is inside it. Without the lock in score_text this fails.
    """
    import threading

    from baseline import score_text

    class _NotThreadSafe:
        """Stands in for the HF pipeline: raises if two threads overlap."""

        def __init__(self):
            self._busy = False
            self.tokenizer = self

        def _enter(self):
            if self._busy:
                raise RuntimeError("Already borrowed")
            self._busy = True

        def _leave(self):
            self._busy = False

        def encode(self, text, add_special_tokens=True):
            self._enter()
            time.sleep(0.005)
            self._leave()
            return [0] * 5

        def __call__(self, texts, **kwargs):
            self._enter()
            time.sleep(0.005)
            self._leave()
            return [[{"label": "Fake", "score": 0.9}]]

    fake = _NotThreadSafe()
    errors: list[BaseException] = []

    def run():
        try:
            score_text("an answer long enough to score")
        except BaseException as exc:  # noqa: BLE001 - the assertion is the report
            errors.append(exc)

    with patch("baseline._pipeline", return_value=fake):
        threads = [threading.Thread(target=run) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert errors == [], f"concurrent scoring raised: {errors!r}"
