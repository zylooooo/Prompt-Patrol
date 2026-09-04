import base64
import binascii
import enum
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth import delete_auth0_user, invite_user
from exceptions import (
    EmailAlreadyExistsError,
    InvalidStatusTransitionError,
    InvalidSupervisorError,
    UserNotFoundError,
)
from models import User, UserRoleEnum, UserSession, UserStatusEnum, UserStatusEvent

logger = logging.getLogger(__name__)


# Normalizes an email address for consistent storage and comparison.
def normalize_email(email: str) -> str:
    return email.strip().lower()


# Normalizes a display label; whitespace-only collapses to NULL, never a blank name.
def normalize_display_name(display_name: str | None) -> str | None:
    if display_name is None:
        return None
    return display_name.strip() or None


class LoginRejection(str, enum.Enum):
    """
    Why a validated Auth0 identity was refused. Distinguishing these lets the
    login page say something true, and lets a removed person still trying the
    door show up in the logs.
    """

    not_provisioned = "not_provisioned"
    deactivated = "deactivated"
    deleted = "deleted"


async def resolve_user(db: AsyncSession, sub: str, email: str) -> User | LoginRejection:
    """
    Checks if the user is allowed to log in by their Auth0 sub. Auth0 sub is used because Auth0 sub is lazily injected upon user creation.
    If the user account is properly created, there will be an Auth0 sub in the database, regardless of user status.
    If Auth0 sub is not found, the user is not authorized to log in.

    Args:
        db (AsyncSession): The database session.
        sub (str): The Auth0 sub of the user.
        email (str): The email of the user.
    
    Returns:
        User: The user object if the user is allowed to log in.
        LoginRejection: The reason for rejection if the user is not allowed to log in.
    """
    email = normalize_email(email)
    result = await db.execute(select(User).where(User.auth0_sub == sub, User.status == UserStatusEnum.active))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    return await _classify_rejection(db, email)


async def _classify_rejection(db: AsyncSession, email: str) -> LoginRejection:
    """Names the reason a login was refused, for the redirect code and the log.

    Safe to report to the user: the address comes from their own validated ID
    token, so they can only ever learn their own status - there is nothing here
    to probe with someone else's address.
    """
    result = await db.execute(select(User.status).where(User.email == email).order_by(User.created_at.desc()))
    existing = result.scalars().first()
    if existing == UserStatusEnum.deactivated:
        logger.warning("Refused sign-in: %s is deactivated.", email)
        return LoginRejection.deactivated
    if existing == UserStatusEnum.deleted:
        logger.warning("Refused sign-in: %s was deleted.", email)
        return LoginRejection.deleted
    logger.info("Refused sign-in: %s is not provisioned.", email)
    return LoginRejection.not_provisioned


_ALLOWED_TRANSITIONS: dict[UserStatusEnum, frozenset[UserStatusEnum]] = {
    UserStatusEnum.active: frozenset({UserStatusEnum.deactivated, UserStatusEnum.deleted}),
    UserStatusEnum.deactivated: frozenset({UserStatusEnum.active, UserStatusEnum.deleted}),
    UserStatusEnum.deleted: frozenset(),
}


# Helper function for authorization checks
def _may_manage(actor: User, target: User) -> bool:
    """Delegation chain as a predicate. _assert_may_manage raises on the same rule."""
    if actor.role == UserRoleEnum.root_admin:
        return True
    if actor.role == UserRoleEnum.instructor:
        return target.role == UserRoleEnum.teaching_assistant and target.provisioned_by == actor.id
    return False


def _assert_may_manage(actor: User, target: User, verb: str) -> None:
    """Delegation chain: TAs manage nobody, instructors manage only the TAs they
    provisioned, root admins manage anyone - but nobody manages themselves."""
    # Self-transition is refused for everyone. A root admin deactivating their
    # own account has their sessions revoked immediately and cannot sign back in,
    # and no one else can reactivate them: instructors may only manage their own
    # TAs. With a single root admin that is a total lockout recoverable only by
    # editing the database - the same one-way door that deletion used to be.
    if actor.id == target.id:
        logger.warning("Actor %s attempted to %s their own account.", actor.id, verb)
        raise PermissionError(f"you cannot {verb} your own account")
    if actor.role == UserRoleEnum.teaching_assistant:
        logger.warning("Actor %s may not %s users.", actor.id, verb)
        raise PermissionError(f"role {actor.role} may not {verb} any users")
    if actor.role == UserRoleEnum.instructor:
        if target.role != UserRoleEnum.teaching_assistant or target.provisioned_by != actor.id:
            logger.warning("Actor %s may not %s user %s.", actor.id, verb, target.id)
            raise PermissionError(f"role {actor.role} may not {verb} user ID: {target.id}")


async def _transition(
    db: AsyncSession,
    actor: User,
    target: User,
    to_status: UserStatusEnum,
    reason: str | None,
) -> User:
    """Validates, applies, revokes sessions and records the event in one commit."""
    # Take the row lock FIRST, and decide the transition from what the locked
    # read returns - not from the earlier unlocked read used for the permission
    # check. Two requests racing on the same user serialise here: the second
    # blocks until the first commits, then sees the status the first left behind
    # and is refused.
    #
    # populate_existing is load-bearing. Without it SQLAlchemy hands back the
    # instance already in this session's identity map with its stale attributes,
    # so the locked read would return the pre-lock status and the guard would
    # pass when it should fail.
    locked = await db.execute(
        select(User).where(User.id == target.id).with_for_update().execution_options(populate_existing=True)
    )
    current = locked.scalar_one()

    from_status = current.status
    if to_status not in _ALLOWED_TRANSITIONS[from_status]:
        raise InvalidStatusTransitionError(f"cannot move a {from_status.value} user to {to_status.value}")

    current.status = to_status

    # Any exit from active must invalidate credentials immediately - a session
    # issued a second before deactivation must not outlive it.
    if to_status != UserStatusEnum.active:
        await db.execute(
            update(UserSession)
            .where(UserSession.user_id == current.id, UserSession.deleted_at.is_(None))
            .values(deleted_at=datetime.now(UTC))
        )

    db.add(
        UserStatusEvent(
            user_id=current.id,
            actor_id=actor.id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
        )
    )
    await db.commit()
    await db.refresh(current)
    logger.info("User %s moved %s -> %s by %s.", current.id, from_status.value, to_status.value, actor.id)
    return current


async def deactivate_user(db: AsyncSession, actor: User, user_id: uuid.UUID, reason: str | None = None) -> User:
    """Removes operational access while keeping the user part of the system."""
    target = await _load_manageable(db, user_id)
    _assert_may_manage(actor, target, "deactivate")
    return await _transition(db, actor, target, UserStatusEnum.deactivated, reason)


async def reactivate_user(db: AsyncSession, actor: User, user_id: uuid.UUID, reason: str | None = None) -> User:
    """Restores access to a deactivated user. Cannot revive a deleted one."""
    target = await _load_manageable(db, user_id)
    _assert_may_manage(actor, target, "reactivate")
    return await _transition(db, actor, target, UserStatusEnum.active, reason)


async def delete_user(db: AsyncSession, actor: User, user_id: uuid.UUID, reason: str | None = None) -> User:
    """
    Logically removes a user. Terminal - there is no restore.

    Root admin only, and never another root admin: deleting one used to be a
    one-way door that no endpoint could undo, and with one root admin it locked
    the whole system out.
    """
    if actor.role != UserRoleEnum.root_admin:
        logger.warning("Actor %s may not delete users.", actor.id)
        raise PermissionError(f"role {actor.role} may not delete users")

    target = await _load_manageable(db, user_id)
    if target.role == UserRoleEnum.root_admin:
        logger.warning("Actor %s attempted to delete a root_admin.", actor.id)
        raise PermissionError("root_admin accounts cannot be deleted")

    deleted = await _transition(db, actor, target, UserStatusEnum.deleted, reason)

    if deleted.auth0_sub is not None:
        # Hard delete useer account in Auth0, only after local soft-delete succeeds.
        if await delete_auth0_user(deleted.auth0_sub):
            # Remove the Auth0 sub in the local row so that when reactivated, provision new account, the Auth0 can be populated again.
            deleted.auth0_sub = None
            await db.commit()
            await db.refresh(deleted)
        else:
            logger.error(
                "User %s was soft-deleted but its Auth0 credential could not be removed - "
                "re-provisioning this email will fail until it's deleted manually or the M2M "
                "app's delete:users scope is fixed.",
                deleted.id,
            )

    return deleted


async def _load_manageable(db: AsyncSession, user_id: uuid.UUID) -> User:
    """Loads any user regardless of status - a deactivated one must stay
    reachable so it can be reactivated."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if target is None:
        raise UserNotFoundError(str(user_id))
    return target


# Returns a visible active user when the requesting actor has permission to view them.
async def get_user_by_id(db: AsyncSession, actor: User, user_id: uuid.UUID) -> User | None:
    logger.debug("Fetching user by ID: %s", user_id)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        logger.debug("No user found with ID: %s", user_id)
        return None

    # A non-active user is visible only to someone who could manage them
    if user.status != UserStatusEnum.active and not _may_manage(actor, user):
        logger.debug("Hiding %s user %s from actor %s.", user.status.value, user_id, actor.id)
        return None

    logger.debug("Authorizationg check for actor: %s requesting user ID: %s", actor, user_id)
    if not _can_view_user(actor, user):
        logger.warning("Actor %s is not authorized to view user ID: %s", actor, user_id)
        return None

    logger.info("User fetched successfully")
    return user


def _can_view_user(actor: User, target: User) -> bool:
    """Who may see whom. The same delegation chain `_may_manage` and
    `list_users` enforce, so a single rule answers "can I read this user?"
    however it is asked.

    It used to be wider than the listing: an instructor could read *any*
    instructor and *any* TA by id while their listing showed only the TAs they
    provisioned, and a TA could read every sibling TA. Two answers to one
    question, and the permissive one was reachable through an endpoint the SPA
    had not wired yet. Narrowed to the delegation chain 2026-08-18.
    """
    if actor.role == UserRoleEnum.root_admin:
        return True
    if actor.id == target.id:
        return True
    if target.role == UserRoleEnum.root_admin:
        return False
    if actor.role == UserRoleEnum.instructor:
        # Exactly what list_users returns for an instructor.
        return target.role == UserRoleEnum.teaching_assistant and target.provisioned_by == actor.id
    if actor.role == UserRoleEnum.teaching_assistant:
        # TAs only can view their own supervisor.
        return target.id == actor.provisioned_by
    return False


# Confirms a proposed supervisor can actually hold the role.
async def _assert_supervisor_available(db: AsyncSession, supervisor_id: uuid.UUID) -> None:
    result = await db.execute(select(User).where(User.id == supervisor_id))
    supervisor = result.scalar_one_or_none()
    if supervisor is None:
        raise InvalidSupervisorError(f"no user with id {supervisor_id}")
    if supervisor.role != UserRoleEnum.instructor:
        raise InvalidSupervisorError("a supervisor must be an instructor")
    if supervisor.status != UserStatusEnum.active:
        raise InvalidSupervisorError("a supervisor must be an active account")


async def _resolve_supervisor(
    db: AsyncSession, actor: User, role: UserRoleEnum, supervisor_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Decides what `provisioned_by` holds on a new account.

    For a teaching assistant this column *is* the supervision edge - the only one
    the schema has - so it names an instructor or nobody at all. For an instructor
    it records who created them and nothing gates on it.
    """
    # Only TAs can have a supervisor.
    if role != UserRoleEnum.teaching_assistant:
        if supervisor_id is not None:
            raise InvalidSupervisorError("only a teaching assistant has a supervisor")
        return actor.id

    if actor.role == UserRoleEnum.instructor:
        # An instructor may only place an assistant under themselves.
        if supervisor_id is not None and supervisor_id != actor.id:
            logger.warning("Instructor %s attempted to assign supervisor %s.", actor.id, supervisor_id)
            raise PermissionError(f"role {actor.role} may not assign another instructor")
        return actor.id

    # Root admin can create TAs without assigning them to any instructor
    if supervisor_id is None:
        return None
    await _assert_supervisor_available(db, supervisor_id)
    return supervisor_id


async def set_supervisor(db: AsyncSession, actor: User, user_id: uuid.UUID, supervisor_id: uuid.UUID | None) -> User:
    """Moves a teaching assistant to another instructor, or unassigns them.

    Placing people is a root admin act. An instructor may only *release* their
    own assistant, never take one: `provisioned_by` is what grants management of
    the row, so letting them assign would let them hand a colleague access, or
    help themselves to someone else's assistant.
    """
    if actor.role == UserRoleEnum.teaching_assistant:
        logger.warning("Actor %s may not reassign supervisors.", actor.id)
        raise PermissionError(f"role {actor.role} may not reassign supervisors")

    target = await _load_manageable(db, user_id)
    if target.role != UserRoleEnum.teaching_assistant:
        raise InvalidSupervisorError("only a teaching assistant has a supervisor")
    if target.status == UserStatusEnum.deleted:
        raise InvalidStatusTransitionError("cannot reassign a deleted user")

    if actor.role == UserRoleEnum.instructor and (supervisor_id is not None or target.provisioned_by != actor.id):
        logger.warning("Instructor %s may not set supervisor %s on %s.", actor.id, supervisor_id, target.id)
        raise PermissionError(f"role {actor.role} may only release their own assistant")

    if supervisor_id is not None:
        await _assert_supervisor_available(db, supervisor_id)

    if target.provisioned_by == supervisor_id:
        return target

    target.provisioned_by = supervisor_id

    # Revoke user's session when they are unassigned from any supervisor.
    if supervisor_id is None:
        await db.execute(
            update(UserSession)
            .where(UserSession.user_id == target.id, UserSession.deleted_at.is_(None))
            .values(deleted_at=datetime.now(UTC))
        )

    await db.commit()
    await db.refresh(target)
    logger.info("Assistant %s assigned to supervisor %s by %s.", target.id, supervisor_id, actor.id)
    return target


# Provisions a new user when the actor has permission to assign the requested role.
# Auth0 emails the invitee their own password-set link directly. 
# Disable Sign Ups means that's the only way they get a credential.
async def create_user(
    db: AsyncSession,
    actor: User,
    email: str,
    role: UserRoleEnum,
    display_name: str | None = None,
    supervisor_id: uuid.UUID | None = None,
) -> User:
    logger.debug("Attempting to create user with email: %s and role: %s by actor: %s", email, role, actor)

    email = normalize_email(email)

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

    provisioned_by = await _resolve_supervisor(db, actor, role, supervisor_id)

    # Every row for this email, most recent first, search for all duplicate roles in case there are duplicates.
    existing = await db.execute(select(User).where(User.email == email).order_by(User.created_at.desc()))
    existing_rows = existing.scalars().all()
    if any(row.status != UserStatusEnum.deleted for row in existing_rows):
        logger.warning("Attempted to provision duplicate email: %s", email)
        raise EmailAlreadyExistsError(email)
    # reuse the most recently deleted row if it exists, otherwise create a new one. This prevents further duplicates
    reusable = existing_rows[0] if existing_rows else None

    # Get the Auth0 sub to lazily inject into the local row.
    auth0_user_id = await invite_user(email)

    # Update the reusable row if it exists
    if reusable is not None:
        reusable.role = role
        reusable.display_name = normalize_display_name(display_name)
        reusable.provisioned_by = provisioned_by
        reusable.auth0_sub = auth0_user_id
        reusable.status = UserStatusEnum.active
        user = reusable
        db.add(
            UserStatusEvent(
                user_id=user.id,
                actor_id=actor.id,
                from_status=UserStatusEnum.deleted,
                to_status=UserStatusEnum.active,
                reason="reprovisioned with a new Auth0 credential",
            )
        )
    else:
        user = User(
            email=email,
            role=role,
            display_name=normalize_display_name(display_name),
            provisioned_by=provisioned_by,
            auth0_sub=auth0_user_id,
        )
        db.add(user)

    try:
        await db.commit()
    except Exception:
        # Rollback mechanism and log out the user from Auth0 if the commit fails.
        await db.rollback()
        await delete_auth0_user(auth0_user_id)
        raise
    await db.refresh(user)
    logger.info("User created successfully")

    return user


# Encodes a user ID as a URL-safe pagination cursor.
def _encode_cursor(user_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(str(user_id).encode()).decode()


# Decodes and validates a URL-safe pagination cursor as a user ID.
def _decode_cursor(cursor: str) -> uuid.UUID:
    try:
        return uuid.UUID(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("Invalid cursor") from exc


# Lists users visible to the actor and returns a cursor for the next page.
async def list_users(
    db: AsyncSession,
    actor: User,
    role: UserRoleEnum | None = None,
    statuses: frozenset[UserStatusEnum] | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[list[User], str | None]:
    logger.debug("Listing users requested by actor: %s", actor.id)
    if actor.role == UserRoleEnum.teaching_assistant:
        logger.warning("Actor %s with role %s cannot list users.", actor.id, actor.role)
        raise PermissionError(f"role {actor.role} may not list users")

    query = select(User)

    if actor.role == UserRoleEnum.instructor:
        # An instructor's directory is the TAs they provisioned
        if role is not None and role != UserRoleEnum.teaching_assistant:
            logger.warning("Actor %s may not list role %s.", actor.id, role)
            raise PermissionError(f"role {actor.role} may not list role {role}")
        query = query.where(User.role == UserRoleEnum.teaching_assistant, User.provisioned_by == actor.id)
    elif role is not None:
        query = query.where(User.role == role)

    # Default is operational: active users only
    query = query.where(User.status.in_(statuses or {UserStatusEnum.active}))

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
