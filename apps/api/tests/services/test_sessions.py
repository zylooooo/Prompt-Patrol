import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from models import User, UserRoleEnum
from models.session import UserSession
from services import authenticate_session, create_session, revoke_session
from services.sessions import SESSION_ABSOLUTE_TTL, SESSION_IDLE_TTL


@pytest.mark.asyncio
async def test_create_then_authenticate_session_roundtrip(db_session):
    user = User(id=uuid.uuid4(), email="c@smu.edu.sg", entra_oid="oid-c", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    raw_token = await create_session(db_session, user.id)
    resolved = await authenticate_session(db_session, raw_token)
    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_authenticate_bumps_last_active_at(db_session):
    user = User(id=uuid.uuid4(), email="d@smu.edu.sg", entra_oid="oid-d", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)

    row = (await db_session.execute(select(UserSession))).scalar_one()
    original_last_active = row.last_active_at

    await authenticate_session(db_session, raw_token)
    await db_session.refresh(row)
    assert row.last_active_at >= original_last_active


@pytest.mark.asyncio
async def test_expired_session_rejected(db_session):
    user = User(id=uuid.uuid4(), email="e@smu.edu.sg", entra_oid="oid-e", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    from auth.tokens import generate_session_token, hash_token

    raw_token = generate_session_token()
    expired = UserSession(
        id=uuid.uuid4(),
        token_hash=hash_token(raw_token),
        user_id=user.id,
        absolute_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    db_session.add(expired)
    await db_session.commit()

    assert await authenticate_session(db_session, raw_token) is None


@pytest.mark.asyncio
async def test_revoked_session_rejected(db_session):
    user = User(id=uuid.uuid4(), email="f@smu.edu.sg", entra_oid="oid-f", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)

    await revoke_session(db_session, raw_token)
    assert await authenticate_session(db_session, raw_token) is None


@pytest.mark.asyncio
async def test_idle_session_rejected(db_session):
    user = User(id=uuid.uuid4(), email="g@smu.edu.sg", entra_oid="oid-g", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    from auth.tokens import generate_session_token, hash_token

    raw_token = generate_session_token()
    now = datetime.now(UTC)
    idle = UserSession(
        id=uuid.uuid4(),
        token_hash=hash_token(raw_token),
        user_id=user.id,
        last_active_at=now - SESSION_IDLE_TTL - timedelta(minutes=1),
        absolute_expires_at=now + SESSION_ABSOLUTE_TTL,
    )
    db_session.add(idle)
    await db_session.commit()

    assert await authenticate_session(db_session, raw_token) is None


@pytest.mark.asyncio
async def test_session_just_inside_the_idle_window_is_accepted(db_session):
    # The other side of the boundary. Shortening the idle window by accident
    # evicts people mid-read, which is the failure the current value is chosen
    # to avoid - so it is asserted rather than left implied.
    user = User(id=uuid.uuid4(), email="h@smu.edu.sg", entra_oid="oid-h", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    from auth.tokens import generate_session_token, hash_token

    raw_token = generate_session_token()
    now = datetime.now(UTC)
    nearly_idle = UserSession(
        id=uuid.uuid4(),
        token_hash=hash_token(raw_token),
        user_id=user.id,
        last_active_at=now - SESSION_IDLE_TTL + timedelta(minutes=1),
        absolute_expires_at=now + SESSION_ABSOLUTE_TTL,
    )
    db_session.add(nearly_idle)
    await db_session.commit()

    resolved = await authenticate_session(db_session, raw_token)
    assert resolved is not None
    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_activity_does_not_extend_the_absolute_cap(db_session):
    # The cap is a hard ceiling, not a second sliding window. Sliding it would
    # make a session immortal for as long as someone keeps clicking.
    user = User(id=uuid.uuid4(), email="i@smu.edu.sg", entra_oid="oid-i", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    raw_token = await create_session(db_session, user.id)

    row = (await db_session.execute(select(UserSession))).scalar_one()
    original_cap = row.absolute_expires_at

    await authenticate_session(db_session, raw_token)
    await db_session.refresh(row)

    assert row.absolute_expires_at == original_cap


@pytest.mark.asyncio
async def test_unknown_token_rejected(db_session):
    assert await authenticate_session(db_session, "not-a-real-token") is None
