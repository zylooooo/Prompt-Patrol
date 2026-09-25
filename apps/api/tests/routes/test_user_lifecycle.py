import uuid
from datetime import UTC, datetime

import pytest

from main import app
from models import User, UserRoleEnum, UserStatusEnum
from services import create_session


# POST /api/users calls out to Auth0's Management + Authentication APIs
# (DECISION LOG [0.9.0]). These tests exercise the route/service, not that
# HTTP call.
@pytest.fixture(autouse=True)
def _stub_invite_user(monkeypatch):
    async def fake_invite_user(email):
        return None

    async def fake_find(email):
        return None

    monkeypatch.setattr("services.users_service.invite_user", fake_invite_user)
    monkeypatch.setattr("services.users_service.find_auth0_user_id_by_email", fake_find)


async def _signed_in(client, db_session, role):
    actor = User(id=uuid.uuid4(), email=f"{role.value}@smu.edu.sg", role=role)
    db_session.add(actor)
    await db_session.commit()
    client.cookies.set("__Host-session", await create_session(db_session, actor.id))
    return actor


async def _target(
    db_session,
    role=UserRoleEnum.teaching_assistant,
    provisioned_by=None,
    status=UserStatusEnum.active,
    signed_in=True,
):
    # signed_in=False is a pending invite (first_login_at null).
    user = User(
        id=uuid.uuid4(),
        email=f"target-{uuid.uuid4()}@smu.edu.sg",
        role=role,
        provisioned_by=provisioned_by,
        status=status,
        first_login_at=datetime.now(UTC) if signed_in else None,
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_deactivate_endpoint_returns_the_new_status(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session)

    response = await client.post(f"/api/users/{target.id}/deactivate", json={"reason": "semester ended"})

    assert response.status_code == 200
    assert response.json()["status"] == "deactivated"


@pytest.mark.asyncio
async def test_reactivate_endpoint_returns_the_new_status(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session, status=UserStatusEnum.deactivated)

    response = await client.post(f"/api/users/{target.id}/reactivate")

    assert response.status_code == 200
    assert response.json()["status"] == "active"


@pytest.mark.asyncio
async def test_delete_endpoint_is_refused_to_an_instructor(client, db_session):
    # Deletion is terminal, so it sits above the reversible deactivation an
    # instructor performs on their own TA.
    instructor = await _signed_in(client, db_session, UserRoleEnum.instructor)
    target = await _target(db_session, provisioned_by=instructor.id)

    assert (await client.request("DELETE", f"/api/users/{target.id}")).status_code == 403


@pytest.mark.asyncio
async def test_delete_endpoint_allows_a_root_admin(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session)

    response = await client.request("DELETE", f"/api/users/{target.id}", json={"reason": "left"})

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_reactivating_a_deleted_user_is_a_conflict(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session, status=UserStatusEnum.deleted)

    assert (await client.post(f"/api/users/{target.id}/reactivate")).status_code == 409


@pytest.mark.asyncio
async def test_transition_on_unknown_user_is_404(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    assert (await client.post(f"/api/users/{uuid.uuid4()}/deactivate")).status_code == 404


def test_there_is_no_restore_endpoint():
    # Deletion is terminal by design. Re-granting access means provisioning a
    # fresh account, which is visible and audited.
    assert not [p for p in app.openapi()["paths"] if "restore" in p]


@pytest.mark.asyncio
async def test_listing_hides_deleted_users_unless_asked(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    gone = await _target(db_session, status=UserStatusEnum.deleted)

    default = (await client.get("/api/users/")).json()["items"]
    assert str(gone.id) not in [u["id"] for u in default]

    widened = (await client.get("/api/users/?status=deleted")).json()["items"]
    assert str(gone.id) in [u["id"] for u in widened]


# --- display_name -----------------------------------------------------------


@pytest.mark.asyncio
async def test_provisioning_round_trips_a_display_name(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    created = await client.post(
        "/api/users/",
        json={"email": "new@smu.edu.sg", "role": "instructor", "display_name": "Amirah Rahman"},
    )

    assert created.status_code == 201
    assert created.json()["display_name"] == "Amirah Rahman"
    assert (await client.get(f"/api/users/{created.json()['id']}")).json()["display_name"] == "Amirah Rahman"


@pytest.mark.asyncio
async def test_display_name_is_optional(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    created = await client.post("/api/users/", json={"email": "plain@smu.edu.sg", "role": "instructor"})

    assert created.status_code == 201
    assert created.json()["display_name"] is None


@pytest.mark.asyncio
async def test_an_over_long_display_name_is_rejected(client, db_session):
    # Bounded at the schema so a pasted document cannot become a name.
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    response = await client.post(
        "/api/users/",
        json={"email": "long@smu.edu.sg", "role": "instructor", "display_name": "x" * 201},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_provisioning_still_rejects_unknown_fields(client, db_session):
    # extra="forbid" is what keeps the request from carrying its own status or
    # provisioned_by. Adding display_name must not have loosened it.
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    response = await client.post(
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

    await client.post(f"/api/users/{victim.id}/deactivate")

    client.cookies.clear()
    client.cookies.set("__Host-session", victim_token)
    assert (await client.get("/api/auth/me")).status_code == 401
    assert admin.id is not None


@pytest.mark.asyncio
async def test_listing_caps_the_page_size(client, db_session):
    """`limit` was unbounded, so one request could ask for the whole table.
    Callers page with `cursor` instead."""
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    assert (await client.get("/api/users/?limit=100")).status_code == 200
    assert (await client.get("/api/users/?limit=101")).status_code == 422
    assert (await client.get("/api/users/?limit=0")).status_code == 422


@pytest.mark.asyncio
async def test_instructor_listing_a_role_outside_their_scope_is_403(client, db_session):
    """Not an empty 200. An instructor's directory is the TAs they provisioned;
    asking for instructors is refused, so "you may not" cannot be mistaken for
    "there are none"."""
    await _signed_in(client, db_session, UserRoleEnum.instructor)

    assert (await client.get("/api/users/?role=instructor")).status_code == 403
    assert (await client.get("/api/users/?role=teaching_assistant")).status_code == 200


@pytest.mark.asyncio
async def test_reading_a_user_outside_the_delegation_chain_is_404(client, db_session):
    """The read rule now matches the listing. Both "no such user" and "not
    yours" answer 404, so the endpoint cannot be used to enumerate accounts."""
    instructor = await _signed_in(client, db_session, UserRoleEnum.instructor)
    own = await _target(db_session, provisioned_by=instructor.id)
    another_instructor = await _target(db_session, role=UserRoleEnum.instructor)
    someone_elses = await _target(db_session, provisioned_by=another_instructor.id)

    assert (await client.get(f"/api/users/{own.id}")).status_code == 200
    assert (await client.get(f"/api/users/{someone_elses.id}")).status_code == 404
    assert (await client.get(f"/api/users/{another_instructor.id}")).status_code == 404


# --- assigning a supervisor -------------------------------------------------
# The SPA used to hold "who supervises whom" in localStorage, so an admin's pick
# of instructor never reached the database and the roster read Unassigned in every
# other browser. These are the two routes that make the pick real.


@pytest.mark.asyncio
async def test_provisioning_accepts_a_supervising_instructor(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    instructor = await _target(db_session, role=UserRoleEnum.instructor)

    response = await client.post(
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

    response = await client.post(
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

    response = await client.post(
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

    response = await client.post(
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

    response = await client.post(
        f"/api/users/{assistant.id}/supervisor",
        json={"supervisor_id": str(admin.id)},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_an_instructor_cannot_provision_under_a_colleague(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.instructor)
    colleague = await _target(db_session, role=UserRoleEnum.instructor)

    response = await client.post(
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

    response = await client.post(
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

    response = await client.post(f"/api/users/{assistant.id}/supervisor", json={"supervisor_id": None})

    assert response.status_code == 200
    assert response.json()["provisioned_by"] is None


@pytest.mark.asyncio
async def test_supervisor_endpoint_is_refused_to_an_instructor(client, db_session):
    # Reassignment is an admin act: the column is what grants an instructor
    # management of the row, so they cannot hand it to a colleague.
    instructor = await _signed_in(client, db_session, UserRoleEnum.instructor)
    colleague = await _target(db_session, role=UserRoleEnum.instructor)
    assistant = await _target(db_session, provisioned_by=instructor.id)

    response = await client.post(
        f"/api/users/{assistant.id}/supervisor",
        json={"supervisor_id": str(colleague.id)},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_supervisor_endpoint_hides_an_unknown_user(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)

    response = await client.post(f"/api/users/{uuid.uuid4()}/supervisor", json={"supervisor_id": None})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_supervisor_endpoint_refuses_a_deleted_assistant(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    instructor = await _target(db_session, role=UserRoleEnum.instructor)
    assistant = await _target(db_session, status=UserStatusEnum.deleted)

    response = await client.post(
        f"/api/users/{assistant.id}/supervisor",
        json={"supervisor_id": str(instructor.id)},
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_supervisor_endpoint_rejects_unknown_fields(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    assistant = await _target(db_session)

    response = await client.post(
        f"/api/users/{assistant.id}/supervisor",
        json={"supervisor_id": None, "role": "root_admin"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_an_instructor_can_release_their_own_assistant_over_the_wire(client, db_session):
    instructor = await _signed_in(client, db_session, UserRoleEnum.instructor)
    assistant = await _target(db_session, provisioned_by=instructor.id)

    response = await client.post(f"/api/users/{assistant.id}/supervisor", json={"supervisor_id": None})

    assert response.status_code == 200
    assert response.json()["provisioned_by"] is None


@pytest.mark.asyncio
async def test_an_assistant_cannot_reach_the_supervisor_endpoint(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.teaching_assistant)
    target = await _target(db_session)

    response = await client.post(f"/api/users/{target.id}/supervisor", json={"supervisor_id": None})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_resend_invite_endpoint_maps_outcomes(client, db_session, monkeypatch):
    sent = []

    async def fake_resend(email):
        sent.append(email)

    monkeypatch.setattr("services.users_service.resend_invite_email", fake_resend)
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    pending = await _target(db_session, signed_in=False)

    ok = await client.post(f"/api/users/{pending.id}/resend-invite")
    assert ok.status_code == 200
    assert ok.json()["first_login_at"] is None
    assert sent == [pending.email]

    missing = await client.post(f"/api/users/{uuid.uuid4()}/resend-invite")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_resend_invite_endpoint_is_refused_to_signed_in_users(client, db_session, monkeypatch):
    async def fake_resend(email):
        return None

    monkeypatch.setattr("services.users_service.resend_invite_email", fake_resend)
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session)

    assert (await client.post(f"/api/users/{target.id}/resend-invite")).status_code == 409


# --- status-change reason ---------------------------------------------------


async def _events(db_session, user_id):
    from sqlalchemy import select

    from models import UserStatusEvent

    rows = await db_session.execute(select(UserStatusEvent).where(UserStatusEvent.user_id == user_id))
    return list(rows.scalars())


@pytest.mark.asyncio
async def test_deactivate_stores_the_reason_on_the_event(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session)

    response = await client.post(f"/api/users/{target.id}/deactivate", json={"reason": "semester ended"})

    assert response.status_code == 200
    (event,) = await _events(db_session, target.id)
    assert event.reason == "semester ended"


@pytest.mark.asyncio
async def test_a_reason_is_stored_without_markup_or_control_characters(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session)

    response = await client.post(
        f"/api/users/{target.id}/deactivate",
        json={"reason": "  <script>alert(1)</script> left\x00 the course\nsee note  "},
    )

    assert response.status_code == 200
    (event,) = await _events(db_session, target.id)
    assert event.reason == "scriptalert(1)/script left the course\nsee note"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, {}, {"reason": None}, {"reason": "   "}, {"reason": "<>"}])
async def test_a_missing_or_blank_reason_is_stored_as_null(client, db_session, body):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session)

    response = await client.post(f"/api/users/{target.id}/deactivate", json=body)

    assert response.status_code == 200
    (event,) = await _events(db_session, target.id)
    assert event.reason is None


@pytest.mark.asyncio
async def test_an_over_long_reason_is_rejected_and_changes_nothing(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session)

    response = await client.post(f"/api/users/{target.id}/deactivate", json={"reason": "x" * 501})

    assert response.status_code == 422
    assert await _events(db_session, target.id) == []


@pytest.mark.asyncio
async def test_reactivate_stores_its_reason_too(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    target = await _target(db_session, status=UserStatusEnum.deactivated)

    await client.post(f"/api/users/{target.id}/reactivate", json={"reason": "back for summer term"})

    (event,) = await _events(db_session, target.id)
    assert event.reason == "back for summer term"


@pytest.mark.asyncio
async def test_an_instructor_can_deactivate_and_reactivate_their_own_assistant(client, db_session):
    instructor = await _signed_in(client, db_session, UserRoleEnum.instructor)
    assistant = await _target(db_session, provisioned_by=instructor.id)

    off = await client.post(f"/api/users/{assistant.id}/deactivate", json={"reason": "on leave"})
    on = await client.post(f"/api/users/{assistant.id}/reactivate")

    assert (off.status_code, off.json()["status"]) == (200, "deactivated")
    assert (on.status_code, on.json()["status"]) == (200, "active")
    assert [e.reason for e in sorted(await _events(db_session, assistant.id), key=lambda e: e.to_status.value)] == [
        None,
        "on leave",
    ]


@pytest.mark.asyncio
async def test_an_instructor_cannot_deactivate_or_reactivate_someone_elses_assistant(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.instructor)
    colleague = await _target(db_session, role=UserRoleEnum.instructor)
    theirs = await _target(db_session, provisioned_by=colleague.id)
    theirs_off = await _target(db_session, provisioned_by=colleague.id, status=UserStatusEnum.deactivated)

    assert (await client.post(f"/api/users/{theirs.id}/deactivate")).status_code == 403
    assert (await client.post(f"/api/users/{theirs_off.id}/reactivate")).status_code == 403


@pytest.mark.asyncio
async def test_an_instructor_can_deactivate_a_pending_assistant(client, db_session):
    # Pending (never signed in) is display-only; it must not fence deactivation.
    instructor = await _signed_in(client, db_session, UserRoleEnum.instructor)
    pending = await _target(db_session, provisioned_by=instructor.id, signed_in=False)

    response = await client.post(f"/api/users/{pending.id}/deactivate", json={"reason": "wrong email"})

    assert response.status_code == 200
    assert response.json()["status"] == "deactivated"
    (event,) = await _events(db_session, pending.id)
    assert event.reason == "wrong email"


@pytest.mark.asyncio
async def test_a_root_admin_can_deactivate_or_delete_a_pending_user(client, db_session):
    await _signed_in(client, db_session, UserRoleEnum.root_admin)
    to_pause = await _target(db_session, signed_in=False)
    to_delete = await _target(db_session, signed_in=False)

    assert (await client.post(f"/api/users/{to_pause.id}/deactivate")).status_code == 200
    assert (await client.request("DELETE", f"/api/users/{to_delete.id}")).status_code == 200
