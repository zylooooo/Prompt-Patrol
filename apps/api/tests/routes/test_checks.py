import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from db import get_db
from detection.baseline import Score
from main import app
from models import User, UserRoleEnum
from routes.checks import require_any_user


@pytest.fixture
def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _authed_request(client, user):
    async def override():
        return user

    client.app.dependency_overrides[require_any_user] = override
    return client


AI_LIKE = "Furthermore, this ensures the system consequently facilitates a robust outcome."
HUMAN_LIKE = "idk it just kinda works because we set the pointer to null before freeing it"


@pytest.mark.asyncio
async def test_create_check_without_session_returns_401(client):
    response = client.post("/api/checks", json={"answer_text": HUMAN_LIKE})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_check_happy_path(client, db_session):
    user = User(id=uuid.uuid4(), email="ta@smu.edu.sg", role=UserRoleEnum.teaching_assistant)
    _authed_request(client, user)

    with patch("services.checks.score_text", return_value=Score(raw_score=0.9, truncated=False)):
        response = client.post(
            "/api/checks",
            json={"answer_text": AI_LIKE, "strictness": "standard"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] == "ai_generated"
    assert body["raw_score"] == 0.9
    assert body["actor_id"] == str(user.id)
    assert body["detector"]["model_version"]
    assert body["detector"]["used_question_text"] is False
    assert response.headers["location"] == f"/api/checks/{body['check_id']}"


@pytest.mark.asyncio
async def test_create_check_abstains_on_short_answer(client, db_session):
    user = User(id=uuid.uuid4(), email="ta2@smu.edu.sg", role=UserRoleEnum.teaching_assistant)
    _authed_request(client, user)

    with patch("services.checks.score_text", return_value=Score(raw_score=0.9, truncated=False)):
        response = client.post(
            "/api/checks",
            json={"answer_text": "too short reply"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] == "uncertain"
    assert body["abstain_reason"] == "answer_too_short"


@pytest.mark.asyncio
async def test_create_check_rejects_unknown_field(client, db_session):
    user = User(id=uuid.uuid4(), email="ta3@smu.edu.sg", role=UserRoleEnum.teaching_assistant)
    _authed_request(client, user)

    response = client.post(
        "/api/checks",
        json={"answer_text": HUMAN_LIKE, "instructor_id": str(uuid.uuid4())},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_check_rejects_too_short_below_floor(client, db_session):
    user = User(id=uuid.uuid4(), email="ta4@smu.edu.sg", role=UserRoleEnum.teaching_assistant)
    _authed_request(client, user)

    response = client.post("/api/checks", json={"answer_text": "short"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_get_detector_capabilities(client, db_session):
    user = User(id=uuid.uuid4(), email="ta5@smu.edu.sg", role=UserRoleEnum.teaching_assistant)
    _authed_request(client, user)

    response = client.get("/api/detector")
    assert response.status_code == 200
    body = response.json()
    assert body["requires_question_text"] is False
    assert {level["level"] for level in body["strictness_levels"]} == {
        "lenient",
        "standard",
        "strict",
    }
