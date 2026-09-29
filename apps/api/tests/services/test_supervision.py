import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from exceptions import (
    Auth0ProvisioningError,
    CannotAddTeachingAssistantError,
    InvalidStatusTransitionError,
    InvalidSupervisorError,
    UserNotFoundError,
)
from models import Supervision, User, UserRoleEnum, UserSession, UserStatusEnum
from schemas import UserResponse
from services import create_session
from services.users_service import (
    add_teaching_assistant,
    change_user_role,
    deactivate_user,
    delete_user,
    end_supervision,
    link_supervisor,
    reactivate_user,
)


def _person(role, status=UserStatusEnum.active):
    uid = uuid.uuid4()
    return User(id=uid, email=f"{role.value}-{uid}@smu.edu.sg", role=role, status=status)


async def _supervise(db, ta, *instructors):
    """Test shortcut for an active link. Services go through _link instead."""
    db.add_all(Supervision(ta_id=ta.id, instructor_id=i.id) for i in instructors)
    await db.commit()
    await db.refresh(ta)


# --- what counts as a supervisor ---------------------------------------------
# DECISION LOG [0.21.0]: an active link to an active instructor. Ended links are
# history; a deactivated instructor's links come back when they do.


@pytest.mark.asyncio
async def test_supervisor_ids_counts_active_links_to_active_instructors(db_session):
    teaching = _person(UserRoleEnum.instructor)
    moved_on = _person(UserRoleEnum.instructor)
    on_leave = _person(UserRoleEnum.instructor, UserStatusEnum.deactivated)
    ta = _person(UserRoleEnum.teaching_assistant)
    db_session.add_all([teaching, moved_on, on_leave, ta])
    await db_session.commit()
    db_session.add(Supervision(ta_id=ta.id, instructor_id=moved_on.id, ended_at=datetime.now(UTC)))
    await _supervise(db_session, ta, teaching, on_leave)

    assert ta.supervisor_ids == [teaching.id]


@pytest.mark.asyncio
async def test_supervisor_ids_is_loaded_by_a_plain_query(db_session):
    # Async sessions cannot lazy-load; reading the property after an ordinary
    # select must not raise MissingGreenlet. Needs join_depth on the relationship.
    instructor, ta = _person(UserRoleEnum.instructor), _person(UserRoleEnum.teaching_assistant)
    db_session.add_all([instructor, ta])
    await db_session.commit()
    await _supervise(db_session, ta, instructor)
    db_session.expunge_all()

    loaded = (await db_session.execute(select(User).where(User.id == ta.id))).scalar_one()

    assert loaded.supervisor_ids == [instructor.id]


@pytest.mark.asyncio
async def test_a_pair_has_at_most_one_active_link(db_session):
    instructor, ta = _person(UserRoleEnum.instructor), _person(UserRoleEnum.teaching_assistant)
    db_session.add_all([instructor, ta])
    await db_session.commit()
    # Any number of ended links is fine - they are history.
    db_session.add_all(
        Supervision(ta_id=ta.id, instructor_id=instructor.id, ended_at=datetime.now(UTC)) for _ in range(2)
    )
    await _supervise(db_session, ta, instructor)

    db_session.add(Supervision(ta_id=ta.id, instructor_id=instructor.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_the_response_carries_supervisor_ids(db_session):
    instructor, ta = _person(UserRoleEnum.instructor), _person(UserRoleEnum.teaching_assistant)
    db_session.add_all([instructor, ta])
    await db_session.commit()
    await _supervise(db_session, ta, instructor)
    await db_session.refresh(instructor)  # built in this session: nothing loaded its supervisors yet

    assert UserResponse.model_validate(ta).supervisor_ids == [instructor.id]
    assert UserResponse.model_validate(instructor).supervisor_ids == []


async def _people(db, *people):
    db.add_all(people)
    await db.commit()
    return people


async def _live_sessions(db, user_id):
    result = await db.execute(
        select(UserSession).where(UserSession.user_id == user_id, UserSession.deleted_at.is_(None))
    )
    return result.scalars().all()


# --- root_admin places a TA ----------------------------------------------------


@pytest.mark.asyncio
async def test_linking_adds_a_supervisor_and_keeps_the_others(db_session):
    admin, first, second, ta = await _people(
        db_session,
        _person(UserRoleEnum.root_admin),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
    )
    await _supervise(db_session, ta, first)

    linked = await link_supervisor(db_session, admin, ta.id, second.id)

    assert sorted(linked.supervisor_ids) == sorted([first.id, second.id])


@pytest.mark.asyncio
async def test_linking_an_existing_pair_is_a_no_op(db_session):
    admin, instructor, ta = await _people(
        db_session,
        _person(UserRoleEnum.root_admin),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
    )
    await link_supervisor(db_session, admin, ta.id, instructor.id)

    again = await link_supervisor(db_session, admin, ta.id, instructor.id)

    assert again.supervisor_ids == [instructor.id]
    rows = await db_session.execute(select(Supervision).where(Supervision.ta_id == ta.id))
    assert len(rows.scalars().all()) == 1


@pytest.mark.asyncio
async def test_only_root_admin_links(db_session):
    instructor, ta = await _people(
        db_session, _person(UserRoleEnum.instructor), _person(UserRoleEnum.teaching_assistant)
    )

    with pytest.raises(PermissionError):
        await link_supervisor(db_session, instructor, ta.id, instructor.id)


@pytest.mark.asyncio
async def test_linking_checks_both_ends(db_session):
    admin, instructor, off, ta, gone_ta = await _people(
        db_session,
        _person(UserRoleEnum.root_admin),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.instructor, UserStatusEnum.deactivated),
        _person(UserRoleEnum.teaching_assistant),
        _person(UserRoleEnum.teaching_assistant, UserStatusEnum.deactivated),
    )

    with pytest.raises(InvalidSupervisorError):  # target is not a TA
        await link_supervisor(db_session, admin, instructor.id, instructor.id)
    with pytest.raises(InvalidSupervisorError):  # supervisor is not active
        await link_supervisor(db_session, admin, ta.id, off.id)
    with pytest.raises(InvalidStatusTransitionError):  # TA is not active
        await link_supervisor(db_session, admin, gone_ta.id, instructor.id)
    with pytest.raises(UserNotFoundError):
        await link_supervisor(db_session, admin, uuid.uuid4(), instructor.id)


# --- "Remove from team" ------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_instructor_ends_only_their_own_link(db_session):
    mine, theirs, ta = await _people(
        db_session,
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
    )
    await _supervise(db_session, ta, mine, theirs)

    # Naming a colleague is 404-shaped: it must not confirm their team.
    with pytest.raises(UserNotFoundError):
        await end_supervision(db_session, mine, ta.id, theirs.id)

    left = await end_supervision(db_session, mine, ta.id, mine.id)

    assert left.supervisor_ids == [theirs.id]
    ended = (await db_session.execute(select(Supervision).where(Supervision.instructor_id == mine.id))).scalar_one()
    assert ended.ended_at is not None and ended.ended_by == mine.id


@pytest.mark.asyncio
async def test_ending_a_link_that_does_not_exist_is_not_found(db_session):
    instructor, ta = await _people(
        db_session, _person(UserRoleEnum.instructor), _person(UserRoleEnum.teaching_assistant)
    )

    with pytest.raises(UserNotFoundError):
        await end_supervision(db_session, instructor, ta.id, instructor.id)


@pytest.mark.asyncio
async def test_ending_the_last_link_signs_the_assistant_out(db_session):
    first, second, ta = await _people(
        db_session,
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
    )
    await _supervise(db_session, ta, first, second)
    await create_session(db_session, ta.id)

    await end_supervision(db_session, first, ta.id, first.id)
    assert len(await _live_sessions(db_session, ta.id)) == 1  # still supervised by `second`

    await end_supervision(db_session, second, ta.id, second.id)
    assert await _live_sessions(db_session, ta.id) == []


@pytest.mark.asyncio
async def test_root_admin_can_end_any_link(db_session):
    admin, instructor, ta = await _people(
        db_session,
        _person(UserRoleEnum.root_admin),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
    )
    await _supervise(db_session, ta, instructor)

    left = await end_supervision(db_session, admin, ta.id, instructor.id)

    assert left.supervisor_ids == []


@pytest.mark.asyncio
async def test_deleting_either_end_ends_the_link(db_session):
    admin, instructor, ta, other_ta = await _people(
        db_session,
        _person(UserRoleEnum.root_admin),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
        _person(UserRoleEnum.teaching_assistant),
    )
    await _supervise(db_session, ta, instructor)
    await _supervise(db_session, other_ta, instructor)

    await delete_user(db_session, admin, ta.id)
    await delete_user(db_session, admin, instructor.id)

    active = await db_session.execute(select(Supervision).where(Supervision.ended_at.is_(None)))
    assert active.scalars().all() == []


@pytest.mark.asyncio
async def test_changing_role_ends_links_but_resubmitting_the_same_role_does_not(db_session):
    admin, instructor, ta = await _people(
        db_session,
        _person(UserRoleEnum.root_admin),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
    )
    await _supervise(db_session, ta, instructor)

    same = await change_user_role(db_session, admin, ta.id, UserRoleEnum.teaching_assistant)
    assert same.supervisor_ids == [instructor.id]

    promoted = await change_user_role(db_session, admin, ta.id, UserRoleEnum.instructor)
    assert promoted.supervisor_ids == []


@pytest.mark.asyncio
async def test_deactivation_keeps_links_so_reactivation_restores_the_team(db_session):
    admin, instructor, ta = await _people(
        db_session,
        _person(UserRoleEnum.root_admin),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
    )
    await _supervise(db_session, ta, instructor)

    await deactivate_user(db_session, admin, instructor.id)
    await db_session.refresh(ta)
    assert ta.supervisor_ids == []  # a deactivated instructor stops counting

    await reactivate_user(db_session, admin, instructor.id)
    await db_session.refresh(ta)
    assert ta.supervisor_ids == [instructor.id]


# --- no active supervisor, no session ------------------------------------------
# DECISION LOG [0.22.0]: every write that can remove a TA's last active
# supervisor signs the TA out in the same commit.


async def _lose(db, action, admin, instructor):
    if action == "delete":
        await delete_user(db, admin, instructor.id)
    elif action == "role":
        await change_user_role(db, admin, instructor.id, UserRoleEnum.teaching_assistant)
    else:
        await deactivate_user(db, admin, instructor.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["delete", "role", "deactivate"])
async def test_losing_the_last_instructor_signs_the_assistant_out(db_session, action):
    admin, instructor, ta = await _people(
        db_session,
        _person(UserRoleEnum.root_admin),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
    )
    await _supervise(db_session, ta, instructor)
    await create_session(db_session, ta.id)

    await _lose(db_session, action, admin, instructor)

    assert await _live_sessions(db_session, ta.id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["delete", "role", "deactivate"])
async def test_an_assistant_with_another_instructor_stays_signed_in(db_session, action):
    admin, leaving, staying, ta = await _people(
        db_session,
        _person(UserRoleEnum.root_admin),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
    )
    await _supervise(db_session, ta, leaving, staying)
    await create_session(db_session, ta.id)

    await _lose(db_session, action, admin, leaving)

    assert len(await _live_sessions(db_session, ta.id)) == 1


@pytest.mark.asyncio
async def test_a_deactivated_co_instructor_does_not_keep_the_assistant_signed_in(db_session):
    admin, leaving, on_leave, ta = await _people(
        db_session,
        _person(UserRoleEnum.root_admin),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
    )
    await _supervise(db_session, ta, leaving, on_leave)
    await create_session(db_session, ta.id)

    await deactivate_user(db_session, admin, on_leave.id)
    assert len(await _live_sessions(db_session, ta.id)) == 1  # `leaving` still counts

    await delete_user(db_session, admin, leaving.id)
    assert await _live_sessions(db_session, ta.id) == []


@pytest.mark.asyncio
async def test_reactivating_the_instructor_restores_the_team_but_not_the_session(db_session):
    admin, instructor, ta = await _people(
        db_session,
        _person(UserRoleEnum.root_admin),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
    )
    await _supervise(db_session, ta, instructor)
    await create_session(db_session, ta.id)

    await deactivate_user(db_session, admin, instructor.id)
    await reactivate_user(db_session, admin, instructor.id)

    await db_session.refresh(ta)
    assert ta.supervisor_ids == [instructor.id]
    assert await _live_sessions(db_session, ta.id) == []


@pytest.mark.asyncio
async def test_resubmitting_an_instructors_role_signs_no_one_out(db_session):
    admin, instructor, ta = await _people(
        db_session,
        _person(UserRoleEnum.root_admin),
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
    )
    await _supervise(db_session, ta, instructor)
    await create_session(db_session, ta.id)

    await change_user_role(db_session, admin, instructor.id, UserRoleEnum.instructor)

    assert len(await _live_sessions(db_session, ta.id)) == 1


@pytest.mark.asyncio
async def test_only_root_admin_deactivates_or_reactivates(db_session):
    instructor, ta, off = await _people(
        db_session,
        _person(UserRoleEnum.instructor),
        _person(UserRoleEnum.teaching_assistant),
        _person(UserRoleEnum.teaching_assistant, UserStatusEnum.deactivated),
    )
    await _supervise(db_session, ta, instructor)
    await _supervise(db_session, off, instructor)

    with pytest.raises(PermissionError):
        await deactivate_user(db_session, instructor, ta.id)
    with pytest.raises(PermissionError):
        await reactivate_user(db_session, instructor, off.id)


# --- instructors add a TA by email (DECISION LOG [0.21.0]) --------------------
# Every success looks the same and every refusal looks the same; these pin the
# outcome table, not the wording (that is the route's job).


@pytest.fixture
def invites(monkeypatch):
    """Records invite_user calls. A link must never reach Auth0."""
    sent = []

    async def fake_invite_user(email):
        sent.append(email)
        return f"auth0|{email}"

    async def fake_find(email):
        return None

    monkeypatch.setattr("services.users_service.invite_user", fake_invite_user)
    monkeypatch.setattr("services.users_service.find_auth0_user_id_by_email", fake_find)
    return sent


@pytest.mark.asyncio
async def test_a_new_email_is_invited_and_joins_the_callers_team(db_session, invites):
    (instructor,) = await _people(db_session, _person(UserRoleEnum.instructor))

    added = await add_teaching_assistant(db_session, instructor, "  New.TA@SMU.edu.sg ")

    assert invites == ["new.ta@smu.edu.sg"]
    assert added.role == UserRoleEnum.teaching_assistant
    assert added.provisioned_by == instructor.id
    assert added.display_name is None
    assert added.supervisor_ids == [instructor.id]


@pytest.mark.asyncio
async def test_an_active_ta_is_linked_without_touching_their_account(db_session, invites):
    first, second = await _people(db_session, _person(UserRoleEnum.instructor), _person(UserRoleEnum.instructor))
    ta = _person(UserRoleEnum.teaching_assistant)
    ta.display_name, ta.provisioned_by, ta.auth0_sub = "Wei Lin", first.id, "auth0|wei"
    await _people(db_session, ta)
    await _supervise(db_session, ta, first)

    added = await add_teaching_assistant(db_session, second, ta.email)

    assert invites == []
    assert sorted(added.supervisor_ids) == sorted([first.id, second.id])
    assert (added.display_name, added.provisioned_by, added.auth0_sub) == ("Wei Lin", first.id, "auth0|wei")


@pytest.mark.asyncio
async def test_adding_a_ta_already_on_the_team_changes_nothing(db_session, invites):
    instructor, ta = await _people(
        db_session, _person(UserRoleEnum.instructor), _person(UserRoleEnum.teaching_assistant)
    )
    await _supervise(db_session, ta, instructor)

    again = await add_teaching_assistant(db_session, instructor, ta.email)

    assert again.supervisor_ids == [instructor.id]
    rows = await db_session.execute(select(Supervision).where(Supervision.ta_id == ta.id))
    assert len(rows.scalars().all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "status"),
    [
        (UserRoleEnum.teaching_assistant, UserStatusEnum.deactivated),
        (UserRoleEnum.teaching_assistant, UserStatusEnum.deleted),
        (UserRoleEnum.instructor, UserStatusEnum.active),
        (UserRoleEnum.instructor, UserStatusEnum.deactivated),
        (UserRoleEnum.root_admin, UserStatusEnum.active),
    ],
)
async def test_anything_but_a_new_email_or_an_active_ta_is_refused(db_session, invites, role, status):
    (instructor,) = await _people(db_session, _person(UserRoleEnum.instructor))
    (existing,) = await _people(db_session, _person(role, status))

    with pytest.raises(CannotAddTeachingAssistantError):
        await add_teaching_assistant(db_session, instructor, existing.email)

    assert invites == []  # a deleted email is not re-provisioned here - root_admin's call


@pytest.mark.asyncio
async def test_only_an_instructor_adds_teaching_assistants(db_session, invites):
    admin, ta = await _people(db_session, _person(UserRoleEnum.root_admin), _person(UserRoleEnum.teaching_assistant))

    for actor in (admin, ta):
        with pytest.raises(PermissionError):
            await add_teaching_assistant(db_session, actor, "someone@smu.edu.sg")


@pytest.mark.asyncio
async def test_a_failed_invite_saves_nothing(db_session, monkeypatch):
    (instructor,) = await _people(db_session, _person(UserRoleEnum.instructor))

    async def refuse(email):
        raise Auth0ProvisioningError("down")

    async def fake_find(email):
        return None

    monkeypatch.setattr("services.users_service.invite_user", refuse)
    monkeypatch.setattr("services.users_service.find_auth0_user_id_by_email", fake_find)

    with pytest.raises(Auth0ProvisioningError):
        await add_teaching_assistant(db_session, instructor, "nobody@smu.edu.sg")

    assert (await db_session.execute(select(User).where(User.email == "nobody@smu.edu.sg"))).first() is None
