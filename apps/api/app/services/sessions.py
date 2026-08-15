import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import generate_session_token, hash_token
from models import User, UserSession

# 30 min sliding idle timeout, 4h hard cap that never gets extended.
SESSION_ABSOLUTE_TTL = timedelta(hours=4)
SESSION_IDLE_TTL = timedelta(minutes=30)


async def create_session(db: AsyncSession, user_id: uuid.UUID) -> str:
    # Called from the callback route after Entra login succeeds. Returns the
    # raw token so the caller can set it as the cookie, only the hash gets
    # written to the DB.
    raw_token = generate_session_token()
    now = datetime.now(timezone.utc)
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


async def authenticate_session(db: AsyncSession, raw_token: str) -> User | None:
    # Called on every reqeust with the dependency. Returns None for any
    # invalid/expired/revoked/deleted-user case, we don't distinguish which
    # one it was, there's no reason for a caller to know why a session died.
    # A successful lookup bumps last_active_at, sliding the idle window.
    token_hash = hash_token(raw_token)
    now = datetime.now(timezone.utc)
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


async def revoke_session(db: AsyncSession, raw_token: str) -> None:
    # Soft delete only, only set the deleted_at.
    token_hash = hash_token(raw_token)
    await db.execute(
        update(UserSession)
        .where(UserSession.token_hash == token_hash, UserSession.deleted_at.is_(None))
        .values(deleted_at=datetime.now(timezone.utc))
    )
    await db.commit()
