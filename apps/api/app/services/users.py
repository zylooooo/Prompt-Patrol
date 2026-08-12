import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from models.session import UserSession


async def resolve_or_bind_user(db: AsyncSession, oid: str, email: str) -> User | None:
    """Called from the callback route after Entra hands back claims.

    There's no self-service signup here, a users row has to already exist
    (an admin provisions it via scripts/provision_user.py) before someone's
    first login. We try matching on entra_oid first, that's the normal path
    for every login after the first. If that misses, fall back to matching
    on email and bind the oid to that row, which is what lets an admin
    provision someone before they've ever logged in. No match on either one
    means they're not provisioned, so we return None.
    """
    result = await db.execute(select(User).where(User.entra_oid == oid, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    result = await db.execute(select(User).where(User.email == email, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is None:
        return None

    user.entra_oid = oid
    await db.commit()
    await db.refresh(user)
    return user


async def soft_delete_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Marks the user deleted_at and revokes (soft-deletes) all their
    sessions in the same operation, so a deactivated account can't keep
    using a still-live cookie."""
    now = datetime.now(timezone.utc)
    await db.execute(update(User).where(User.id == user_id).values(deleted_at=now))
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.deleted_at.is_(None))
        .values(deleted_at=now)
    )
    await db.commit()
