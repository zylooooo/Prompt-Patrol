import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from exceptions import InvalidStatusTransitionError, InvalidSupervisorError, UserNotFoundError
from models import Supervision, User, UserRoleEnum, UserSession, UserStatusEnum
from schemas import UserResponse
from services import create_session
from services.users_service import (
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
