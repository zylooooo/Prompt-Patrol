import uuid
import logging

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import User, UserRoleEnum
from models.session import UserSession

logger = logging.getLogger(__name__)


async def resolve_or_bind_user(db: AsyncSession, oid: str, email: str) -> User | None:
    """
    Called from the callback route after Entra hands back claims.

    There's no self-service signup here, a users row has to already exist
    for successful login. We try matching on entra_oid first, that's the normal 
    path for every login after the first. If that misses, fall back to matching
    on email and bind the oid to that row, which is what lets an admin
    provision someone before they've ever logged in. No match on either one
    means they're not provisioned, so we return None.
    """
    # Authenticated users can not first time logging in
    result = await db.execute(select(User).where(User.entra_oid == oid, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    # Case where user accounts created but on user's first sign in.
    result = await db.execute(select(User).where(User.email == email, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is None:
        return None

    # Bind the entra oid if is the user's first log in.
    user.entra_oid = oid
    await db.commit()
    await db.refresh(user)
    return user


async def soft_delete_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """
    Marks the user deleted_at and revokes (soft-deletes) all their
    sessions in the same operation, so a deactivated account can't keep
    using a still-live cookie.
    """
    now = datetime.now(timezone.utc)
    await db.execute(update(User).where(User.id == user_id).values(deleted_at=now))
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.deleted_at.is_(None))
        .values(deleted_at=now)
    )
    await db.commit()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """
    Fetches a user by their ID. Returns None if the user doesn't exist or has been soft-deleted.

    Args:
        db (AsyncSession): The database session.
        user_id (uuid.UUID): The ID of the user to fetch.
    
    Returns:
        User | None: The user object if found and not soft-deleted, otherwise None.
    """
    logger.debug("Fetching user by ID: %s", user_id)
    result = await db.execute(
        select(User).where(
            User.id == user_id, User.deleted_at.is_(None)
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        logger.debug("No user found with ID: %s or user is soft-deleted.", user_id)
        return None

    logger.info("User fetched successfully")
    return user


def can_view_user(actor: User, target: User) -> bool:
    """Helper function to determine visibility of account.
    root_admin sees everyone, everyone sees themselves, instructors see other 
    instructors/TAs, TAs see any instructor plus TAs sharing their own provisioned_by. root_admin 
    rows are never visible to a non-admin."""
    # Can consider changing the TA filtering logic if we eventually implemnet a join table
    # to better store relationships between instructors and TAs.
    if actor.role == UserRoleEnum.root_admin:
        return True
    if actor.id == target.id:
        return True
    if target.role == UserRoleEnum.root_admin:
        return False
    if actor.role == UserRoleEnum.instructor:
        return target.role in (UserRoleEnum.instructor, UserRoleEnum.teaching_assistant)
    if actor.role == UserRoleEnum.teaching_assistant:
        if target.role == UserRoleEnum.instructor:
            return True
        return target.role == UserRoleEnum.teaching_assistant and target.provisioned_by == actor.provisioned_by
    return False
