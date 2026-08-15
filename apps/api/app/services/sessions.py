import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import generate_session_token, hash_token
from models import User, UserSession

SESSION_ABSOLUTE_TTL = timedelta(hours=12)
SESSION_IDLE_TTL = timedelta(minutes=90)


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


# Validates a session, refreshes its activity timestamp, and returns its user.
async def authenticate_session(db: AsyncSession, raw_token: str) -> User | None:
    token_hash = hash_token(raw_token)
    now = datetime.now(UTC)
    result = await db.execute(
        select(UserSession, User)
        .join(User, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == token_hash,
            UserSession.deleted_at.is_(None),
            UserSession.absolute_expires_at > now,
            UserSession.last_active_at > now - SESSION_IDLE_TTL,
            User.deleted_at.is_(None),
        )
    )
    row = result.first()
    if row is None:
        return None
    session_row, user_row = row
    session_row.last_active_at = now
    await db.commit()
    return user_row


# Revokes an active session and returns the user associated with it.
async def revoke_session(db: AsyncSession, raw_token: str) -> User | None:
    token_hash = hash_token(raw_token)
    result = await db.execute(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(UserSession.token_hash == token_hash, UserSession.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    await db.execute(
        update(UserSession)
        .where(UserSession.token_hash == token_hash, UserSession.deleted_at.is_(None))
        .values(deleted_at=datetime.now(UTC))
    )
    await db.commit()
    return user
