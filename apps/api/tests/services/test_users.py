import uuid

import pytest

from models import UserRoleEnum, User
from services.users_service import can_view_user, resolve_or_bind_user, soft_delete_user


def _user(role, provisioned_by=None):
    return User(id=uuid.uuid4(), email=f"{role.value}@smu.edu.sg", role=role, provisioned_by=provisioned_by)


def test_root_admin_sees_everyone():
    admin = _user(UserRoleEnum.root_admin)
    other_admin = _user(UserRoleEnum.root_admin)
    assert can_view_user(admin, other_admin) is True


def test_everyone_sees_themselves():
    ta = _user(UserRoleEnum.teaching_assistant)
    assert can_view_user(ta, ta) is True


def test_root_admin_invisible_to_non_admin():
    instructor = _user(UserRoleEnum.instructor)
    admin = _user(UserRoleEnum.root_admin)
    assert can_view_user(instructor, admin) is False


def test_instructor_sees_other_instructor_and_ta():
    instructor = _user(UserRoleEnum.instructor)
    other_instructor = _user(UserRoleEnum.instructor)
    ta = _user(UserRoleEnum.teaching_assistant)
    assert can_view_user(instructor, other_instructor) is True
    assert can_view_user(instructor, ta) is True


def test_ta_sees_any_instructor():
    ta = _user(UserRoleEnum.teaching_assistant)
    instructor = _user(UserRoleEnum.instructor)
    assert can_view_user(ta, instructor) is True


def test_ta_sees_sibling_ta_same_provisioner_only():
    instructor_id = uuid.uuid4()
    other_instructor_id = uuid.uuid4()
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor_id)
    sibling_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor_id)
    unrelated_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=other_instructor_id)
    assert can_view_user(ta, sibling_ta) is True
    assert can_view_user(ta, unrelated_ta) is False


@pytest.mark.asyncio
async def test_resolve_by_oid_when_already_bound(db_session):
    user = User(id=uuid.uuid4(), email="a@smu.edu.sg", entra_oid="oid-1", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="oid-1", email="different@smu.edu.sg")
    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_binds_oid_on_first_login_via_email_fallback(db_session):
    user = User(id=uuid.uuid4(), email="a@smu.edu.sg", entra_oid=None, role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="oid-new", email="a@smu.edu.sg")
    assert resolved.id == user.id
    assert resolved.entra_oid == "oid-new"


@pytest.mark.asyncio
async def test_oid_match_wins_over_conflicting_email_match(db_session):
    # Two distinct rows: one matches by entra_oid, a *different* row would
    # match by email if email were checked first. oid lookup must win and
    # the email-matching row must be left untouched.
    oid_user = User(id=uuid.uuid4(), email="oid-owner@smu.edu.sg", entra_oid="oid-shared", role=UserRoleEnum.instructor)
    email_user = User(id=uuid.uuid4(), email="conflict@smu.edu.sg", entra_oid=None, role=UserRoleEnum.instructor)
    db_session.add_all([oid_user, email_user])
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="oid-shared", email="conflict@smu.edu.sg")

    assert resolved.id == oid_user.id
    await db_session.refresh(email_user)
    assert email_user.entra_oid is None


@pytest.mark.asyncio
async def test_unprovisioned_email_returns_none(db_session):
    resolved = await resolve_or_bind_user(db_session, oid="oid-x", email="nobody@smu.edu.sg")
    assert resolved is None


@pytest.mark.asyncio
async def test_soft_deleted_user_not_resolved(db_session):
    user = User(
        id=uuid.uuid4(),
        email="gone@smu.edu.sg",
        entra_oid="oid-gone",
        role=UserRoleEnum.instructor,
        deleted_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    db_session.add(user)
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="oid-gone", email="gone@smu.edu.sg")
    assert resolved is None


@pytest.mark.asyncio
async def test_soft_delete_user_cascades_to_sessions(db_session):
    from services import authenticate_session, create_session

    user = User(id=uuid.uuid4(), email="b@smu.edu.sg", entra_oid="oid-b", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)

    await soft_delete_user(db_session, user.id)

    assert await authenticate_session(db_session, raw_token) is None
