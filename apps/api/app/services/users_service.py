import uuid
import logging

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import EmailAlreadyExistsError, UserNotDeletedError
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


async def soft_delete_user(db: AsyncSession, actor: User, user_id: uuid.UUID) -> None:
    """
    Marks the user deleted_at and revokes (soft-deletes) all their
    sessions in the same operation, so a deactivated account can't keep
    using a still-live cookie. Root admins can delete any user, instructors can only
    delete TAs they provisoned, and TAs can't delete anyone.

    Args:
        db (AsyncSession): The database session.
        actor (User): The user requesting the deletion, used for authorization checks.
        user_id (uuid.UUID): The ID of the user to delete.
    
    Raises:
        PermissionError: If the actor is not authorized to delete the target user.
    """
    logger.debug("Attempting to soft delete user with ID: %s by actor: %s", user_id, actor.id)
    if actor.role == UserRoleEnum.teaching_assistant:
        logger.warning("Actor %s attempted to delete a user. Insufficient permissions.", actor.id)
        raise PermissionError(f"role {actor.role} may not delete any users")

    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    target_user = result.scalar_one_or_none()
    if target_user is None:
        logger.info("No target user found for soft deletion")
        return None
    
    if actor.role == UserRoleEnum.instructor:
        if target_user.role != UserRoleEnum.teaching_assistant or target_user.provisioned_by != actor.id:
            logger.warning("Actor %s with role %s cannot delete user ID: %s. Insufficient permissions.", actor.id, actor.role, user_id)
            raise PermissionError(f"role {actor.role} may not delete user ID: {user_id}")

    # Soft delete the user and their sessions.
    now = datetime.now(timezone.utc)
    await db.execute(update(User).where(User.id == user_id).values(deleted_at=now))
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.deleted_at.is_(None))
        .values(deleted_at=now)
    )
    await db.commit()
    logger.info("Successfully deleted user.")


async def get_user_by_id(db: AsyncSession, actor: User, user_id: uuid.UUID) -> User | None:
    """
    Fetches a user by their ID. Returns None if the user doesn't exist or has been soft-deleted.

    Args:
        db (AsyncSession): The database session.
        actor (uuid.UUID): The ID of the user making the request, used for authorization.
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
    
    logger.debug("Authorizationg check for actor: %s requesting user ID: %s", actor, user_id)
    if not _can_view_user(actor, user):
        logger.warning("Actor %s is not authorized to view user ID: %s", actor, user_id)
        return None

    logger.info("User fetched successfully")
    return user


def _can_view_user(actor: User, target: User) -> bool:
    """
    Helper function to determine visibility of account.
    root_admin sees everyone, everyone sees themselves, instructors see other 
    instructors/TAs, TAs see any instructor plus TAs sharing their own provisioned_by. root_admin 
    rows are never visible to a non-admin.
    """
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


async def create_user(db: AsyncSession, actor: User, email: str, role: UserRoleEnum) -> User:
    """
    Creates a new user in the database, per the delegation chain:
    root_admin -> instructor, instructor -> teaching_assistant, TA -> nobody.
    `role=root_admin` is rejected regardless of actor - there is exactly one,
    created only by the seed migration.

    Args:
        db (AsyncSession): The database session.
        email (str): The email of the new user.
        role (UserRoleEnum): The role of the new user.
        actor (User): The user creating the new user, used for authorization checks.
    
    Returns:
        User: The newly created user object.

    Raises:
        PermissionError: actor's role may not provision the requested role.
        EmailAlreadyExistsError: a users row already exists for this email.
    """
    logger.debug("Attempting to create user with email: %s and role: %s by actor: %s", email, role, actor)

    if role == UserRoleEnum.root_admin:
        logger.warning("Actor %s attempted to provision a root_admin user, always rejected.", actor)
        raise PermissionError("root_admin cannot be provisioned via this endpoint")
    if actor.role == UserRoleEnum.teaching_assistant:
        logger.warning("Actor %s with role %s cannot create users. Insufficient permissions.", actor, actor.role)
        raise PermissionError(f"role {actor.role} may not provision any users")
    if actor.role == UserRoleEnum.instructor and role != UserRoleEnum.teaching_assistant:
        logger.warning("Actor %s with role %s cannot create user with role %s. Insufficient permissions.", actor, actor.role, role)
        raise PermissionError(f"role {actor.role} may not provision role {role}")

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        logger.warning("Attempted to provision duplicate email: %s", email)
        raise EmailAlreadyExistsError(email)

    user = User(email=email, role=role, provisioned_by=actor.id)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("User created successfully")

    return user


async def activate_user_by_id(db: AsyncSession, actor: User, user_id: uuid.UUID) -> User | None:
    """
    Restores a soft-deleted user by clearing deleted_at. Same delegation chain
    as soft_delete_user: root_admin can restore anyone (except root_admin
    targets), instructor can only restore teaching_assistant rows they
    themselves provisioned, TA can't restore anyone.

    Args:
        db (AsyncSession): The database session.
        actor (User): The user requesting the account restoration, used for authorization checks.
        user_id (uuid.UUID): The ID of the user to restore.

    Returns:
        User | None: The restored user object, or None if no user exists with this id.

    Raises:
        PermissionError: If the actor is not authorized to restore the target user.
        UserNotDeletedError: If the target user exists but isn't currently deleted.
    """
    logger.debug("Attempting to restore user with ID: %s requested by actor: %s", user_id, actor.id)
    if actor.role == UserRoleEnum.teaching_assistant:
        logger.warning("Actor %s with role %s cannot restore users. Insufficient permissions.", actor.id, actor.role)
        raise PermissionError(f"role {actor.role} may not restore any users")

    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if target_user is None:
        logger.info("No target user found for restoration")
        return None

    if target_user.role == UserRoleEnum.root_admin:
        logger.warning("Actor %s attempted to restore a root_admin user, always rejected.", actor.id)
        raise PermissionError("root_admin cannot be restored via this endpoint")

    if actor.role == UserRoleEnum.instructor:
        if target_user.role != UserRoleEnum.teaching_assistant or target_user.provisioned_by != actor.id:
            logger.warning("Actor %s with role %s cannot restore user ID: %s. Insufficient permissions.", actor.id, actor.role, user_id)
            raise PermissionError(f"role {actor.role} may not restore user ID: {user_id}")

    if target_user.deleted_at is None:
        logger.info("Target user ID: %s is not currently deleted", user_id)
        raise UserNotDeletedError(str(user_id))

    target_user.deleted_at = None
    await db.commit()
    await db.refresh(target_user)
    logger.info("User restored successfully")

    return target_user
