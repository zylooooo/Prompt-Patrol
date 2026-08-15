import uuid

import pytest
from sqlalchemy import select

from exceptions import EmailAlreadyExistsError
from models import UserRoleEnum, User
from services.users_service import (
    _can_view_user,
    create_user,
    resolve_or_bind_user,
    soft_delete_user,
)


def _user(role, provisioned_by=None, email=None):
    uid = uuid.uuid4()
    return User(id=uid, email=email or f"{role.value}-{uid}@smu.edu.sg", role=role, provisioned_by=provisioned_by)


def test_root_admin_sees_everyone():
    admin = _user(UserRoleEnum.root_admin)
    other_admin = _user(UserRoleEnum.root_admin)
    assert _can_view_user(admin, other_admin) is True


def test_everyone_sees_themselves():
    ta = _user(UserRoleEnum.teaching_assistant)
    assert _can_view_user(ta, ta) is True


def test_root_admin_invisible_to_non_admin():
    instructor = _user(UserRoleEnum.instructor)
    admin = _user(UserRoleEnum.root_admin)
    assert _can_view_user(instructor, admin) is False


def test_instructor_sees_other_instructor_and_ta():
    instructor = _user(UserRoleEnum.instructor)
    other_instructor = _user(UserRoleEnum.instructor)
    ta = _user(UserRoleEnum.teaching_assistant)
    assert _can_view_user(instructor, other_instructor) is True
    assert _can_view_user(instructor, ta) is True


def test_ta_sees_any_instructor():
    ta = _user(UserRoleEnum.teaching_assistant)
    instructor = _user(UserRoleEnum.instructor)
    assert _can_view_user(ta, instructor) is True


def test_ta_sees_sibling_ta_same_provisioner_only():
    instructor_id = uuid.uuid4()
    other_instructor_id = uuid.uuid4()
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor_id)
    sibling_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor_id)
    unrelated_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=other_instructor_id)
    assert _can_view_user(ta, sibling_ta) is True
    assert _can_view_user(ta, unrelated_ta) is False


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

    admin = _user(UserRoleEnum.root_admin)
    user = User(id=uuid.uuid4(), email="b@smu.edu.sg", entra_oid="oid-b", role=UserRoleEnum.instructor)
    db_session.add_all([admin, user])
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)

    await soft_delete_user(db_session, admin, user.id)

    assert await authenticate_session(db_session, raw_token) is None


@pytest.mark.asyncio
async def test_ta_cannot_delete_any_user(db_session):
    ta = _user(UserRoleEnum.teaching_assistant)
    target = _user(UserRoleEnum.teaching_assistant)
    db_session.add_all([ta, target])
    await db_session.commit()

    with pytest.raises(PermissionError):
        await soft_delete_user(db_session, ta, target.id)


@pytest.mark.asyncio
async def test_root_admin_can_delete_anyone(db_session):
    admin = _user(UserRoleEnum.root_admin)
    target = _user(UserRoleEnum.instructor)
    db_session.add_all([admin, target])
    await db_session.commit()

    await soft_delete_user(db_session, admin, target.id)

    await db_session.refresh(target)
    assert target.deleted_at is not None


@pytest.mark.asyncio
async def test_instructor_can_delete_own_ta(db_session):
    instructor = _user(UserRoleEnum.instructor)
    db_session.add(instructor)
    await db_session.commit()
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    db_session.add(ta)
    await db_session.commit()

    await soft_delete_user(db_session, instructor, ta.id)

    await db_session.refresh(ta)
    assert ta.deleted_at is not None


@pytest.mark.asyncio
async def test_instructor_cannot_delete_unrelated_ta(db_session):
    instructor = _user(UserRoleEnum.instructor)
    other_instructor_id = uuid.uuid4()
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=other_instructor_id)
    db_session.add_all([instructor, ta])
    await db_session.commit()

    with pytest.raises(PermissionError):
        await soft_delete_user(db_session, instructor, ta.id)


@pytest.mark.asyncio
async def test_instructor_cannot_delete_instructor(db_session):
    instructor = _user(UserRoleEnum.instructor)
    other_instructor = _user(UserRoleEnum.instructor)
    db_session.add_all([instructor, other_instructor])
    await db_session.commit()

    with pytest.raises(PermissionError):
        await soft_delete_user(db_session, instructor, other_instructor.id)


@pytest.mark.asyncio
async def test_instructor_cannot_delete_root_admin(db_session):
    instructor = _user(UserRoleEnum.instructor)
    admin = _user(UserRoleEnum.root_admin)
    db_session.add_all([instructor, admin])
    await db_session.commit()

    with pytest.raises(PermissionError):
        await soft_delete_user(db_session, instructor, admin.id)


@pytest.mark.asyncio
async def test_delete_nonexistent_user_is_noop(db_session):
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    # No exception, and no row created either - this is idempotent-delete
    # semantics, not an authorization decision.
    await soft_delete_user(db_session, admin, uuid.uuid4())


@pytest.mark.asyncio
async def test_delete_already_deleted_user_is_noop(db_session):
    admin = _user(UserRoleEnum.root_admin)
    target = User(
        id=uuid.uuid4(),
        email="already-gone@smu.edu.sg",
        role=UserRoleEnum.instructor,
        deleted_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    db_session.add_all([admin, target])
    await db_session.commit()

    await soft_delete_user(db_session, admin, target.id)


@pytest.mark.asyncio
async def test_root_admin_creates_instructor(db_session):
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    created = await create_user(db_session, admin, "new-instructor@smu.edu.sg", UserRoleEnum.instructor)

    assert created.email == "new-instructor@smu.edu.sg"
    assert created.role == UserRoleEnum.instructor
    assert created.provisioned_by == admin.id


@pytest.mark.asyncio
async def test_instructor_creates_ta(db_session):
    instructor = _user(UserRoleEnum.instructor)
    db_session.add(instructor)
    await db_session.commit()

    created = await create_user(db_session, instructor, "new-ta@smu.edu.sg", UserRoleEnum.teaching_assistant)

    assert created.role == UserRoleEnum.teaching_assistant
    assert created.provisioned_by == instructor.id


@pytest.mark.asyncio
async def test_ta_cannot_create_any_user(db_session):
    ta = _user(UserRoleEnum.teaching_assistant)
    db_session.add(ta)
    await db_session.commit()

    with pytest.raises(PermissionError):
        await create_user(db_session, ta, "nope@smu.edu.sg", UserRoleEnum.teaching_assistant)


@pytest.mark.asyncio
async def test_instructor_cannot_create_instructor(db_session):
    instructor = _user(UserRoleEnum.instructor)
    db_session.add(instructor)
    await db_session.commit()

    with pytest.raises(PermissionError):
        await create_user(db_session, instructor, "peer@smu.edu.sg", UserRoleEnum.instructor)


@pytest.mark.asyncio
async def test_root_admin_cannot_create_root_admin(db_session):
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    with pytest.raises(PermissionError):
        await create_user(db_session, admin, "another-admin@smu.edu.sg", UserRoleEnum.root_admin)


@pytest.mark.asyncio
async def test_duplicate_email_raises_conflict(db_session):
    admin = _user(UserRoleEnum.root_admin)
    existing = User(id=uuid.uuid4(), email="taken@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add_all([admin, existing])
    await db_session.commit()

    with pytest.raises(EmailAlreadyExistsError):
        await create_user(db_session, admin, "taken@smu.edu.sg", UserRoleEnum.instructor)


@pytest.mark.asyncio
async def test_duplicate_email_raises_conflict_even_if_soft_deleted(db_session):
    admin = _user(UserRoleEnum.root_admin)
    existing = User(
        id=uuid.uuid4(),
        email="gone@smu.edu.sg",
        role=UserRoleEnum.instructor,
        deleted_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    db_session.add_all([admin, existing])
    await db_session.commit()

    with pytest.raises(EmailAlreadyExistsError):
        await create_user(db_session, admin, "gone@smu.edu.sg", UserRoleEnum.instructor)


@pytest.mark.asyncio
async def test_create_user_persists_row(db_session):
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    created = await create_user(db_session, admin, "persisted@smu.edu.sg", UserRoleEnum.instructor)

    result = await db_session.execute(select(User).where(User.id == created.id))
    assert result.scalar_one_or_none() is not None
