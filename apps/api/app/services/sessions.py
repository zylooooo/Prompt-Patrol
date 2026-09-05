import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import ActiveSession, SessionFailure, generate_session_token, hash_token
from models import User, UserSession, UserStatusEnum

logger = logging.getLogger(__name__)

SESSION_ABSOLUTE_TTL = timedelta(hours=12)
SESSION_IDLE_TTL = timedelta(minutes=90)
SESSION_ACTIVITY_RESOLUTION = timedelta(seconds=60)


# Reads a stored timestamp as UTC-aware.
def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# Creates a new session and returns its unhashed token to the caller.
async def create_session(db: AsyncSession, user_id: uuid.UUID) -> str:
    raw_token = generate_session_token()
    now = datetime.now(UTC)
    session_row = UserSession(
        id=uuid.uuid4(),
        token_hash=hash_token(raw_token),
        user_id=user_id,
        created_at=now,
        last_active_at=now,
        absolute_expires_at=now + SESSION_ABSOLUTE_TTL,
    )
    db.add(session_row)
    await db.commit()
    return raw_token


# Validates a session, refreshes its activity timestamp, and returns it.
async def authenticate_session(
    db: AsyncSession, raw_token: str, *, touch: bool = True
) -> ActiveSession | SessionFailure:
    """`touch=False` answers without counting the question as activity.

    The SPA needs to ask "is this session still alive?" at the exact moment its
    own countdown reaches zero. Asking the ordinary way slid `last_active_at`
    and handed back a full fresh window, so an abandoned tab renewed itself
    forever and the idle timeout did not exist. Observed live: the countdown
    hit zero, /api/auth/me answered 200, and the row's age went from 179s to 3s.
    """
    token_hash = hash_token(raw_token)
    now = datetime.now(UTC)

    result = await db.execute(
        select(UserSession, User).join(User, UserSession.user_id == User.id).where(UserSession.token_hash == token_hash)
    )
    row = result.first()
    if row is None:
        return SessionFailure.session_unknown
    session_row, user_row = row

    if user_row.status is not UserStatusEnum.active:
        return SessionFailure.account_deactivated
    if session_row.deleted_at is not None:
        return SessionFailure.session_revoked

    absolute_expires_at = _as_utc(session_row.absolute_expires_at)
    if absolute_expires_at <= now:
        return SessionFailure.session_ended

    idle_expires_at = _as_utc(session_row.last_active_at) + SESSION_IDLE_TTL
    if idle_expires_at <= now:
        return SessionFailure.session_expired

    if touch and now - _as_utc(session_row.last_active_at) >= SESSION_ACTIVITY_RESOLUTION:
        session_row.last_active_at = now
        idle_expires_at = now + SESSION_IDLE_TTL
        await db.commit()

    return ActiveSession(
        user=user_row,
        expires_at=min(absolute_expires_at, idle_expires_at),
        idle_expires_at=idle_expires_at,
        absolute_expires_at=absolute_expires_at,
    )


# Revokes every live session for one user and reports how many were ended.
async def revoke_all_for_user(db: AsyncSession, user_id: uuid.UUID) -> int:
    # deleted_at IS NULL, so an already-revoked row keeps the timestamp that
    # records when it actually ended.
    result = await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.deleted_at.is_(None))
        .values(deleted_at=datetime.now(UTC))
    )
    await db.commit()
    return result.rowcount


async def sign_out_everywhere(db: AsyncSession, raw_token: str) -> User | None:
    """Ends every session this user holds, not just the browser that asked.

    Nothing in the product can reach a session on a device you no longer hold:
    there is no device list, `/api/admin/sessions` is specified but not built,
    and the only other lever is an admin deactivating the whole account. Ending
    just the calling browser would leave someone who signed out on a shared
    machine with no remedy at all. The cost is bounded the other way - sessions
    already die after 90 minutes idle or 12 hours absolute, and signing back in
    is one Auth0 click.

    The user is resolved from a *live* session on purpose: a stale token must not
    be replayable as a "sign this person out everywhere" primitive.
    """
    token_hash = hash_token(raw_token)
    result = await db.execute(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(UserSession.token_hash == token_hash, UserSession.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        return None

    ended = await revoke_all_for_user(db, user.id)
    logger.info("Signed out user %s, ending %d session(s).", user.id, ended)
    return user
