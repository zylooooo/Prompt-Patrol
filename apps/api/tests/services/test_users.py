import uuid

import pytest

from models import UserRoleEnum, User
from services.users import resolve_or_bind_user, soft_delete_user


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
    from services.sessions import authenticate_session, create_session

    user = User(id=uuid.uuid4(), email="b@smu.edu.sg", entra_oid="oid-b", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)

    await soft_delete_user(db_session, user.id)

    assert await authenticate_session(db_session, raw_token) is None
