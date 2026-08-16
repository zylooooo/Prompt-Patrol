import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from auth import SessionFailure
from models import User, UserRoleEnum, UserStatusEnum
from models.session import UserSession
from services import authenticate_session, create_session, revoke_session
from services.sessions import SESSION_ABSOLUTE_TTL, SESSION_ACTIVITY_RESOLUTION, SESSION_IDLE_TTL


async def _user(db_session, email: str, oid: str, **kwargs) -> User:
    user = User(id=uuid.uuid4(), email=email, entra_oid=oid, role=UserRoleEnum.instructor, **kwargs)
    db_session.add(user)
    await db_session.commit()
    return user


async def _session_row(db_session, user: User, **overrides) -> str:
    """Plants a session row with hand-picked timestamps and returns its token."""
    from auth.tokens import generate_session_token, hash_token

    raw_token = generate_session_token()
    now = datetime.now(UTC)
    fields = {
        "last_active_at": now,
        "absolute_expires_at": now + SESSION_ABSOLUTE_TTL,
        **overrides,
    }
    db_session.add(UserSession(id=uuid.uuid4(), token_hash=hash_token(raw_token), user_id=user.id, **fields))
    await db_session.commit()
    return raw_token


@pytest.mark.asyncio
async def test_create_then_authenticate_session_roundtrip(db_session):
    user = await _user(db_session, "c@smu.edu.sg", "oid-c")

    raw_token = await create_session(db_session, user.id)
    resolved = await authenticate_session(db_session, raw_token)

    assert resolved.user.id == user.id


@pytest.mark.asyncio
async def test_authenticate_bumps_last_active_at(db_session):
    user = await _user(db_session, "d@smu.edu.sg", "oid-d")
    # Planted a full resolution window in the past: a session touched seconds
    # ago is deliberately left alone, so a fresh one would prove nothing.
    stale = datetime.now(UTC) - SESSION_ACTIVITY_RESOLUTION - timedelta(seconds=1)
    raw_token = await _session_row(db_session, user, last_active_at=stale)

    await authenticate_session(db_session, raw_token)

    row = (await db_session.execute(select(UserSession))).scalar_one()
    await db_session.refresh(row)
    assert row.last_active_at.replace(tzinfo=UTC) > stale


@pytest.mark.asyncio
async def test_authenticate_skips_the_write_for_a_session_touched_moments_ago(db_session):
    # Every authenticated request used to UPDATE + COMMIT this row. Against a
    # 90-minute window that write buys nothing, and it sits on the hottest path
    # in the app.
    user = await _user(db_session, "d2@smu.edu.sg", "oid-d2")
    recent = datetime.now(UTC) - timedelta(seconds=5)
    raw_token = await _session_row(db_session, user, last_active_at=recent)

    await authenticate_session(db_session, raw_token)

    row = (await db_session.execute(select(UserSession))).scalar_one()
    await db_session.refresh(row)
    assert row.last_active_at.replace(tzinfo=UTC) == recent


@pytest.mark.asyncio
async def test_expired_session_reports_the_absolute_cap(db_session):
    user = await _user(db_session, "e@smu.edu.sg", "oid-e")
    raw_token = await _session_row(db_session, user, absolute_expires_at=datetime.now(UTC) - timedelta(seconds=1))

    assert await authenticate_session(db_session, raw_token) is SessionFailure.session_ended


@pytest.mark.asyncio
async def test_revoked_session_reports_a_revocation(db_session):
    user = await _user(db_session, "f@smu.edu.sg", "oid-f")
    raw_token = await create_session(db_session, user.id)

    await revoke_session(db_session, raw_token)

    assert await authenticate_session(db_session, raw_token) is SessionFailure.session_revoked


@pytest.mark.asyncio
async def test_idle_session_reports_inactivity(db_session):
    user = await _user(db_session, "g@smu.edu.sg", "oid-g")
    raw_token = await _session_row(
        db_session, user, last_active_at=datetime.now(UTC) - SESSION_IDLE_TTL - timedelta(minutes=1)
    )

    assert await authenticate_session(db_session, raw_token) is SessionFailure.session_expired


@pytest.mark.asyncio
async def test_session_just_inside_the_idle_window_is_accepted(db_session):
    # The other side of the boundary. Shortening the idle window by accident
    # evicts people mid-read, which is the failure the current value is chosen
    # to avoid - so it is asserted rather than left implied.
    user = await _user(db_session, "h@smu.edu.sg", "oid-h")
    raw_token = await _session_row(
        db_session, user, last_active_at=datetime.now(UTC) - SESSION_IDLE_TTL + timedelta(minutes=1)
    )

    resolved = await authenticate_session(db_session, raw_token)

    assert not isinstance(resolved, SessionFailure)
    assert resolved.user.id == user.id


@pytest.mark.asyncio
async def test_activity_does_not_extend_the_absolute_cap(db_session):
    # The cap is a hard ceiling, not a second sliding window. Sliding it would
    # make a session immortal for as long as someone keeps clicking.
    user = await _user(db_session, "i@smu.edu.sg", "oid-i")
    raw_token = await _session_row(
        db_session, user, last_active_at=datetime.now(UTC) - SESSION_ACTIVITY_RESOLUTION - timedelta(seconds=1)
    )

    row = (await db_session.execute(select(UserSession))).scalar_one()
    original_cap = row.absolute_expires_at

    await authenticate_session(db_session, raw_token)
    await db_session.refresh(row)

    assert row.absolute_expires_at == original_cap


@pytest.mark.asyncio
async def test_unknown_token_reports_an_unknown_session(db_session):
    assert await authenticate_session(db_session, "not-a-real-token") is SessionFailure.session_unknown


@pytest.mark.asyncio
async def test_a_deactivated_account_outranks_the_revocation_it_causes(db_session):
    # _transition revokes sessions as it deactivates, so both are true at once.
    # "Your access was turned off" is the one the person can act on; being told
    # the session was revoked sends them to sign in again, which cannot work.
    user = await _user(db_session, "j@smu.edu.sg", "oid-j", status=UserStatusEnum.deactivated)
    raw_token = await _session_row(db_session, user, deleted_at=datetime.now(UTC))

    assert await authenticate_session(db_session, raw_token) is SessionFailure.account_deactivated


@pytest.mark.asyncio
async def test_a_live_session_reports_both_deadlines(db_session):
    # The SPA counts down to expires_at and needs the two components to say
    # which limit is about to bite, because only one of them can be pushed back.
    user = await _user(db_session, "k@smu.edu.sg", "oid-k")
    raw_token = await create_session(db_session, user.id)

    resolved = await authenticate_session(db_session, raw_token)

    assert resolved.expires_at == min(resolved.idle_expires_at, resolved.absolute_expires_at)
    assert resolved.idle_expires_at < resolved.absolute_expires_at
    assert resolved.capped is False


@pytest.mark.asyncio
async def test_a_session_near_its_cap_reports_itself_as_capped(db_session):
    # Past this point activity cannot help, so the SPA must stop offering to
    # extend and tell the user they will have to sign in again.
    user = await _user(db_session, "l@smu.edu.sg", "oid-l")
    raw_token = await _session_row(db_session, user, absolute_expires_at=datetime.now(UTC) + SESSION_IDLE_TTL / 2)

    resolved = await authenticate_session(db_session, raw_token)

    assert resolved.capped is True
    assert resolved.expires_at == resolved.absolute_expires_at
