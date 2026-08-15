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
