import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from db import get_db
from main import app
from models import User, UserRoleEnum
from routes.batches_routes import require_any_user
from routes.checks_routes import require_screening

GOOD_CSV = (
    "external_ref,answer_text\n"
    "stu-1,This is a perfectly reasonable answer with enough words.\n"
)


@pytest.fixture
def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


async def _signed_in_instructor(client, db_session):
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    async def override():
        return user

    client.app.dependency_overrides[require_screening] = override
    client.app.dependency_overrides[require_any_user] = override
    return user


@pytest.mark.asyncio
async def test_upload_url_without_session_returns_401(client):
    response = client.post("/api/batches/upload-url", json={"file_name": "a.csv"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_url_happy_path(client, db_session):
    await _signed_in_instructor(client, db_session)

    with patch(
        "routes.batches_routes.generate_upload_url",
        return_value=("https://example.com/put", "batches/key-a.csv"),
    ):
        response = client.post("/api/batches/upload-url", json={"file_name": "a.csv"})

    assert response.status_code == 200
    body = response.json()
    assert body["upload_url"] == "https://example.com/put"
    assert body["upload_key"] == "batches/key-a.csv"


@pytest.mark.asyncio
async def test_create_batch_happy_path(client, db_session):
    user = await _signed_in_instructor(client, db_session)

    with (
        patch("services.batches_service.download_object", return_value=GOOD_CSV),
        patch("services.batches_service.enqueue_row"),
    ):
        response = client.post(
            "/api/batches",
            json={"upload_key": f"batches/{user.id}/key-a.csv", "file_name": "a.csv"},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["row_total"] == 1
    assert body["batch_file_name"] == "a.csv"


@pytest.mark.asyncio
async def test_get_progress_happy_path(client, db_session):
    user = await _signed_in_instructor(client, db_session)

    with (
        patch("services.batches_service.download_object", return_value=GOOD_CSV),
        patch("services.batches_service.enqueue_row"),
    ):
        create_response = client.post(
            "/api/batches",
            json={"upload_key": f"batches/{user.id}/key-a.csv", "file_name": "a.csv"},
        )
    batch_id = create_response.json()["batch_id"]

    response = client.get(f"/api/batches/{batch_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["row_total"] == 1
    assert body["pending"] == 1


@pytest.mark.asyncio
async def test_get_progress_for_unknown_batch_returns_404(client, db_session):
    await _signed_in_instructor(client, db_session)
    response = client.get(f"/api/batches/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cancel_batch_happy_path(client, db_session):
    user = await _signed_in_instructor(client, db_session)

    with (
        patch("services.batches_service.download_object", return_value=GOOD_CSV),
        patch("services.batches_service.enqueue_row"),
    ):
        create_response = client.post(
            "/api/batches",
            json={"upload_key": f"batches/{user.id}/key-a.csv", "file_name": "a.csv"},
        )
    batch_id = create_response.json()["batch_id"]

    with patch("services.batches_service.purge_batch_messages") as mock_purge:
        response = client.post(f"/api/batches/{batch_id}/cancel")
    assert response.status_code == 200
    body = response.json()
    assert body["cancelled"] is True
    assert body["batch"]["cancelled_at"] is not None
    mock_purge.assert_called_once_with(batch_id)


@pytest.mark.asyncio
async def test_cancel_batch_for_unknown_batch_returns_404(client, db_session):
    await _signed_in_instructor(client, db_session)
    response = client.post(f"/api/batches/{uuid.uuid4()}/cancel")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_root_admin_can_view_and_cancel_another_actors_batch(client, db_session):
    owner = await _signed_in_instructor(client, db_session)

    with (
        patch("services.batches_service.download_object", return_value=GOOD_CSV),
        patch("services.batches_service.enqueue_row"),
    ):
        create_response = client.post(
            "/api/batches",
            json={"upload_key": f"batches/{owner.id}/key-a.csv", "file_name": "a.csv"},
        )
    batch_id = create_response.json()["batch_id"]

    admin = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@smu.edu.sg", role=UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    async def override_admin():
        return admin

    client.app.dependency_overrides[require_any_user] = override_admin

    response = client.get(f"/api/batches/{batch_id}")
    assert response.status_code == 200

    with patch("services.batches_service.purge_batch_messages"):
        response = client.post(f"/api/batches/{batch_id}/cancel")
    assert response.status_code == 200
    assert response.json()["cancelled"] is True
