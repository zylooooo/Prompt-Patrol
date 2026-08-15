import base64
import binascii
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import EmailAlreadyExistsError, UserNotDeletedError
from models import User, UserRoleEnum
from models.session import UserSession

logger = logging.getLogger(__name__)


async def resolve_or_bind_user(db: AsyncSession, oid: str, email: str) -> User | None:
    result = await db.execute(select(User).where(User.entra_oid == oid, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    try:
        claimed = await db.execute(
            update(User)
            .where(User.email == email, User.entra_oid.is_(None), User.deleted_at.is_(None))
            .values(entra_oid=oid)
        )
    except IntegrityError:
        await db.rollback()
        logger.warning("Refused to bind an oid already held by a soft-deleted account.")
        return None

    if claimed.rowcount == 1:
        await db.commit()
        result = await db.execute(select(User).where(User.email == email, User.deleted_at.is_(None)))
        return result.scalar_one_or_none()

    await db.rollback()

    result = await db.execute(select(User.entra_oid).where(User.email == email, User.deleted_at.is_(None)))
    bound_oid = result.scalar_one_or_none()
    if bound_oid is not None:
        logger.warning(
            "Rejected Entra login: claim email %s matches an account already bound to a "
            "different identity (incoming oid %s, bound oid %s).",
            email,
            oid,
            bound_oid,
        )
    return None


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
            logger.warning(
                "Actor %s with role %s cannot delete user ID: %s. Insufficient permissions.",
                actor.id,
                actor.role,
                user_id,
            )
            raise PermissionError(f"role {actor.role} may not delete user ID: {user_id}")

    now = datetime.now(UTC)
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
    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
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
        logger.warning(
            "Actor %s with role %s cannot create user with role %s. Insufficient permissions.", actor, actor.role, role
        )
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
            logger.warning(
                "Actor %s with role %s cannot restore user ID: %s. Insufficient permissions.",
                actor.id,
                actor.role,
                user_id,
            )
            raise PermissionError(f"role {actor.role} may not restore user ID: {user_id}")

    if target_user.deleted_at is None:
        logger.info("Target user ID: %s is not currently deleted", user_id)
        raise UserNotDeletedError(str(user_id))

    target_user.deleted_at = None
    await db.commit()
    await db.refresh(target_user)
    logger.info("User restored successfully")

    return target_user


def _encode_cursor(user_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(str(user_id).encode()).decode()


def _decode_cursor(cursor: str) -> uuid.UUID:
    try:
        return uuid.UUID(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("Invalid cursor") from exc


async def list_users(
    db: AsyncSession,
    actor: User,
    role: UserRoleEnum | None = None,
    include_deleted: bool = False,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[list[User], str | None]:
    """
    Delegation-scoped directory listing, keyset-paginated by id ascending.
    root_admin sees everyone; instructorsees only teaching_assistant rows they themselves provisioned.

    Args:
        db (AsyncSession): The database session.
        actor (User): The user requesting the listing, used for authorization/scoping.
        role (UserRoleEnum | None): Optional role filter.
        include_deleted (bool): Whether to include soft-deleted rows.
        limit (int): Max rows to return.
        cursor (str | None): Opaque cursor from a previous page's next_cursor.

    Returns:
        tuple[list[User], str | None]: (items, next_cursor). next_cursor is
        None when there's no further page.

    Raises:
        PermissionError: actor is a teaching_assistant.
        ValueError: cursor is malformed.
    """
    logger.debug("Listing users requested by actor: %s", actor.id)
    if actor.role == UserRoleEnum.teaching_assistant:
        logger.warning("Actor %s with role %s cannot list users.", actor.id, actor.role)
        raise PermissionError(f"role {actor.role} may not list users")

    query = select(User)

    if actor.role == UserRoleEnum.instructor:
        query = query.where(User.role == UserRoleEnum.teaching_assistant, User.provisioned_by == actor.id)
        if role is not None:
            query = query.where(User.role == role)
    elif role is not None:
        query = query.where(User.role == role)

    if not include_deleted:
        query = query.where(User.deleted_at.is_(None))

    if cursor is not None:
        query = query.where(User.id > _decode_cursor(cursor))

    query = query.order_by(User.id).limit(limit + 1)

    result = await db.execute(query)
    rows = list(result.scalars().all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].id)

    logger.info("Listed %d users for actor %s", len(rows), actor.id)
    return rows, next_cursor
