import uuid

import pytest
from fastapi.testclient import TestClient

from db import get_db
from main import app
from models import User, UserRoleEnum, UserStatusEnum
from services import create_session


@pytest.fixture
def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


async def _signed_in(client, db_session, role):
    actor = User(id=uuid.uuid4(), email=f"{role.value}@smu.edu.sg", role=role)
    db_session.add(actor)
    await db_session.commit()
    client.cookies.set("__Host-session", await create_session(db_session, actor.id))
    return actor


async def _target(db_session, role=UserRoleEnum.teaching_assistant, provisioned_by=None, status=UserStatusEnum.active):
    user = User(
        id=uuid.uuid4(),
        email=f"target-{uuid.uuid4()}@smu.edu.sg",
        role=role,
        provisioned_by=provisioned_by,
        status=status,
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_deactivate_endpoint_returns_the_new_status(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session)

    response = client.post(f"/api/users/{target.id}/deactivate", json={"reason": "semester ended"})

    assert response.status_code == 200
    assert response.json()["status"] == "deactivated"


@pytest.mark.asyncio
async def test_reactivate_endpoint_returns_the_new_status(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session, status=UserStatusEnum.deactivated)

    response = client.post(f"/api/users/{target.id}/reactivate")

    assert response.status_code == 200
    assert response.json()["status"] == "active"


@pytest.mark.asyncio
async def test_delete_endpoint_is_refused_to_an_instructor(client, db_session):
    # Deletion is terminal, so it sits above the reversible deactivation an
    # instructor performs on their own TA.
    instructor = await _signed_in(client, db_session, UserRoleEnum.instructor)
    target = await _target(db_session, provisioned_by=instructor.id)

    assert client.request("DELETE", f"/api/users/{target.id}").status_code == 403


@pytest.mark.asyncio
async def test_delete_endpoint_allows_a_root_admin(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session)

    response = client.request("DELETE", f"/api/users/{target.id}", json={"reason": "left"})

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_reactivating_a_deleted_user_is_a_conflict(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session, status=UserStatusEnum.deleted)

    assert client.post(f"/api/users/{target.id}/reactivate").status_code == 409


@pytest.mark.asyncio
async def test_transition_on_unknown_user_is_404(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    assert client.post(f"/api/users/{uuid.uuid4()}/deactivate").status_code == 404


def test_there_is_no_restore_endpoint():
    # Deletion is terminal by design. Re-granting access means provisioning a
    # fresh account, which is visible and audited.
    assert not [p for p in app.openapi()["paths"] if "restore" in p]


@pytest.mark.asyncio
async def test_listing_hides_deleted_users_unless_asked(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    gone = await _target(db_session, status=UserStatusEnum.deleted)

    default = client.get("/api/users/").json()["items"]
    assert str(gone.id) not in [u["id"] for u in default]

    widened = client.get("/api/users/?status=deleted").json()["items"]
    assert str(gone.id) in [u["id"] for u in widened]


# --- display_name -----------------------------------------------------------


@pytest.mark.asyncio
async def test_provisioning_round_trips_a_display_name(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    created = client.post(
        "/api/users/",
        json={"email": "new@smu.edu.sg", "role": "instructor", "display_name": "Amirah Rahman"},
    )

    assert created.status_code == 201
    assert created.json()["display_name"] == "Amirah Rahman"
    assert client.get(f"/api/users/{created.json()['id']}").json()["display_name"] == "Amirah Rahman"


@pytest.mark.asyncio
async def test_display_name_is_optional(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    created = client.post("/api/users/", json={"email": "plain@smu.edu.sg", "role": "instructor"})

    assert created.status_code == 201
    assert created.json()["display_name"] is None


@pytest.mark.asyncio
async def test_an_over_long_display_name_is_rejected(client, db_session):
    # Bounded at the schema so a pasted document cannot become a name.
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    response = client.post(
        "/api/users/",
        json={"email": "long@smu.edu.sg", "role": "instructor", "display_name": "x" * 201},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_provisioning_still_rejects_unknown_fields(client, db_session):
    # extra="forbid" is what keeps the request from carrying its own status or
    # provisioned_by. Adding display_name must not have loosened it.
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    response = client.post(
        "/api/users/",
        json={"email": "sneaky@smu.edu.sg", "role": "instructor", "status": "active"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_deactivated_user_cannot_use_an_existing_session(client, db_session):
    # End to end: the session is live, the status changes, the very next request
    # with the same cookie is refused.
    admin = await _signed_in(client, db_session, UserRoleEnum.root_admin)
    victim = await _target(db_session)
    victim_token = await create_session(db_session, victim.id)

    client.post(f"/api/users/{victim.id}/deactivate")

    client.cookies.clear()
    client.cookies.set("__Host-session", victim_token)
    assert client.get("/api/auth/me").status_code == 401
    assert admin.id is not None
