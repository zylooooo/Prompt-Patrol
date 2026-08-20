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


@pytest.mark.asyncio
async def test_listing_caps_the_page_size(client, db_session):
    """`limit` was unbounded, so one request could ask for the whole table.
    Callers page with `cursor` instead."""
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    assert client.get("/api/users/?limit=100").status_code == 200
    assert client.get("/api/users/?limit=101").status_code == 422
    assert client.get("/api/users/?limit=0").status_code == 422


@pytest.mark.asyncio
async def test_instructor_listing_a_role_outside_their_scope_is_403(client, db_session):
    """Not an empty 200. An instructor's directory is the TAs they provisioned;
    asking for instructors is refused, so "you may not" cannot be mistaken for
    "there are none"."""
    await _signed_in(client, db_session, UserRoleEnum.instructor)

    assert client.get("/api/users/?role=instructor").status_code == 403
    assert client.get("/api/users/?role=teaching_assistant").status_code == 200


@pytest.mark.asyncio
async def test_reading_a_user_outside_the_delegation_chain_is_404(client, db_session):
    """The read rule now matches the listing. Both "no such user" and "not
    yours" answer 404, so the endpoint cannot be used to enumerate accounts."""
    instructor = await _signed_in(client, db_session, UserRoleEnum.instructor)
    own = await _target(db_session, provisioned_by=instructor.id)
    another_instructor = await _target(db_session, role=UserRoleEnum.instructor)
    someone_elses = await _target(db_session, provisioned_by=another_instructor.id)

    assert client.get(f"/api/users/{own.id}").status_code == 200
    assert client.get(f"/api/users/{someone_elses.id}").status_code == 404
    assert client.get(f"/api/users/{another_instructor.id}").status_code == 404


# --- assigning a supervisor -------------------------------------------------
# The SPA used to hold "who supervises whom" in localStorage, so an admin's pick
# of instructor never reached the database and the roster read Unassigned in every
# other browser. These are the two routes that make the pick real.


@pytest.mark.asyncio
async def test_provisioning_accepts_a_supervising_instructor(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    instructor = await _target(db_session, role=UserRoleEnum.instructor)

    response = client.post(
        "/api/users/",
        json={
            "email": "placed@smu.edu.sg",
            "role": "teaching_assistant",
            "supervisor_id": str(instructor.id),
        },
    )

    assert response.status_code == 201
    assert response.json()["provisioned_by"] == str(instructor.id)


@pytest.mark.asyncio
async def test_provisioning_rejects_a_supervisor_who_is_not_an_instructor(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    assistant = await _target(db_session)

    response = client.post(
        "/api/users/",
        json={
            "email": "nested@smu.edu.sg",
            "role": "teaching_assistant",
            "supervisor_id": str(assistant.id),
        },
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_an_admin_cannot_provision_an_assistant_under_themselves(client, db_session):
    # No assistant is ever supervised by an admin. Supervision is what grants
    # management of the row and what the screening gate reads, and both are
    # instructor-shaped - an admin already manages everyone without it. The SPA
    # hides "Manage My Assistants" from admins for the same reason, but that is
    # a courtesy; this is the check that counts.
    admin = await _signed_in(client, db_session, UserRoleEnum.root_admin)

    response = client.post(
        "/api/users/",
        json={
            "email": "under-admin@smu.edu.sg",
            "role": "teaching_assistant",
            "supervisor_id": str(admin.id),
        },
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_an_admin_provisioning_without_a_supervisor_leaves_the_assistant_unassigned(client, db_session):
    # Naming nobody means genuinely unassigned, not "supervised by the admin
    # who typed it" - the assistant cannot screen until an instructor takes them.
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    response = client.post(
        "/api/users/",
        json={"email": "waiting@smu.edu.sg", "role": "teaching_assistant"},
    )

    assert response.status_code == 201
    assert response.json()["provisioned_by"] is None


@pytest.mark.asyncio
async def test_the_supervisor_endpoint_refuses_to_move_an_assistant_under_an_admin(client, db_session):
    # The same rule on the reassignment route. Enforcing it only at creation
    # would leave one door open to the state the model does not allow.
    admin = await _signed_in(client, db_session, UserRoleEnum.root_admin)
    instructor = await _target(db_session, role=UserRoleEnum.instructor)
    assistant = await _target(db_session, provisioned_by=instructor.id)

    response = client.post(
        f"/api/users/{assistant.id}/supervisor",
        json={"supervisor_id": str(admin.id)},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_an_instructor_cannot_provision_under_a_colleague(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.instructor)
    colleague = await _target(db_session, role=UserRoleEnum.instructor)

    response = client.post(
        "/api/users/",
        json={
            "email": "theirs@smu.edu.sg",
            "role": "teaching_assistant",
            "supervisor_id": str(colleague.id),
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_supervisor_endpoint_returns_the_new_assignment(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    instructor = await _target(db_session, role=UserRoleEnum.instructor)
    assistant = await _target(db_session)

    response = client.post(
        f"/api/users/{assistant.id}/supervisor",
        json={"supervisor_id": str(instructor.id)},
    )

    assert response.status_code == 200
    assert response.json()["provisioned_by"] == str(instructor.id)


@pytest.mark.asyncio
async def test_a_null_supervisor_unassigns_over_the_wire(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    instructor = await _target(db_session, role=UserRoleEnum.instructor)
    assistant = await _target(db_session, provisioned_by=instructor.id)

    response = client.post(f"/api/users/{assistant.id}/supervisor", json={"supervisor_id": None})

    assert response.status_code == 200
    assert response.json()["provisioned_by"] is None


@pytest.mark.asyncio
async def test_supervisor_endpoint_is_refused_to_an_instructor(client, db_session):
    # Reassignment is an admin act: the column is what grants an instructor
    # management of the row, so they cannot hand it to a colleague.
    instructor = await _signed_in(client, db_session, UserRoleEnum.instructor)
    colleague = await _target(db_session, role=UserRoleEnum.instructor)
    assistant = await _target(db_session, provisioned_by=instructor.id)

    response = client.post(
        f"/api/users/{assistant.id}/supervisor",
        json={"supervisor_id": str(colleague.id)},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_supervisor_endpoint_hides_an_unknown_user(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    response = client.post(f"/api/users/{uuid.uuid4()}/supervisor", json={"supervisor_id": None})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_supervisor_endpoint_refuses_a_deleted_assistant(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    instructor = await _target(db_session, role=UserRoleEnum.instructor)
    assistant = await _target(db_session, status=UserStatusEnum.deleted)

    response = client.post(
        f"/api/users/{assistant.id}/supervisor",
        json={"supervisor_id": str(instructor.id)},
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_supervisor_endpoint_rejects_unknown_fields(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    assistant = await _target(db_session)

    response = client.post(
        f"/api/users/{assistant.id}/supervisor",
        json={"supervisor_id": None, "role": "root_admin"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_an_instructor_can_release_their_own_assistant_over_the_wire(client, db_session):
    instructor = await _signed_in(client, db_session, UserRoleEnum.instructor)
    assistant = await _target(db_session, provisioned_by=instructor.id)

    response = client.post(f"/api/users/{assistant.id}/supervisor", json={"supervisor_id": None})

    assert response.status_code == 200
    assert response.json()["provisioned_by"] is None


@pytest.mark.asyncio
async def test_an_assistant_cannot_reach_the_supervisor_endpoint(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.teaching_assistant)
    target = await _target(db_session)

    response = client.post(f"/api/users/{target.id}/supervisor", json={"supervisor_id": None})

    assert response.status_code == 403
