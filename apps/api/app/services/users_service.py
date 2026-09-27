import base64
import binascii
import enum
import logging
import uuid
from collections.abc import Collection
from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from auth import delete_auth0_user, find_auth0_user_id_by_email, invite_user, resend_invite_email
from exceptions import (
    Auth0ProvisioningError,
    CannotAddTeachingAssistantError,
    EmailAlreadyExistsError,
    InvalidStatusTransitionError,
    InvalidSupervisorError,
    UserNotFoundError,
)
from models import Supervision, User, UserRoleEnum, UserRoleEvent, UserSession, UserStatusEnum, UserStatusEvent

logger = logging.getLogger(__name__)


# Normalizes an email address for consistent storage and comparison.
def normalize_email(email: str) -> str:
    return email.strip().lower()


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


async def mark_first_login(db: AsyncSession, user: User) -> None:
    """Records the first successful sign-in. Set once, never moved: null means
    the invite is still pending."""
    if user.first_login_at is not None:
        return
    user.first_login_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)


_ALLOWED_TRANSITIONS: dict[UserStatusEnum, frozenset[UserStatusEnum]] = {
    UserStatusEnum.active: frozenset({UserStatusEnum.deactivated, UserStatusEnum.deleted}),
    UserStatusEnum.deactivated: frozenset({UserStatusEnum.active, UserStatusEnum.deleted}),
    UserStatusEnum.deleted: frozenset(),
}


async def _revoke_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Ends every live session in the caller's transaction (no commit), so the
    revocation lands with whatever change caused it."""
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.deleted_at.is_(None))
        .values(deleted_at=datetime.now(UTC))
    )


async def _end_links(db: AsyncSession, user_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Ends every active supervision the user is on, as TA or as instructor. No
    commit - it rides with the delete or role change that needs it."""
    await db.execute(
        update(Supervision)
        .where(
            or_(Supervision.ta_id == user_id, Supervision.instructor_id == user_id),
            Supervision.ended_at.is_(None),
        )
        .values(ended_at=datetime.now(UTC), ended_by=actor_id)
    )


async def _supervised_ta_ids(db: AsyncSession, instructor_id: uuid.UUID) -> list[uuid.UUID]:
    """TAs with an active link to this user: the only ones a change to this
    user can leave unsupervised. Empty for anyone who is not an instructor."""
    result = await db.execute(
        select(Supervision.ta_id).where(Supervision.instructor_id == instructor_id, Supervision.ended_at.is_(None))
    )
    return list(result.scalars())


async def _sign_out_unsupervised(db: AsyncSession, ta_ids: Collection[uuid.UUID]) -> None:
    """Revokes the live sessions of any of these TAs left with no active
    supervisor (DECISION LOG [0.22.0]). "Active supervisor" matches
    User.supervisors: an active link to an active instructor. No commit - it
    rides with the change that removed the supervisor."""
    if not ta_ids:
        return
    # The subquery must see this transaction's own link ends and status changes.
    await db.flush()
    still_supervised = (
        select(Supervision.ta_id)
        .join(User, User.id == Supervision.instructor_id)
        .where(Supervision.ended_at.is_(None), User.status == UserStatusEnum.active)
    )
    await db.execute(
        update(UserSession)
        .where(
            UserSession.user_id.in_(ta_ids),
            UserSession.user_id.not_in(still_supervised),
            UserSession.deleted_at.is_(None),
        )
        .values(deleted_at=datetime.now(UTC))
    )


def _supervises(actor: User, target: User) -> bool:
    """An instructor holds a TA through an active supervision link, whoever
    provisioned them (DECISION LOG [0.21.0])."""
    return target.role == UserRoleEnum.teaching_assistant and actor.id in target.supervisor_ids


# Helper function for authorization checks
def _may_manage(actor: User, target: User) -> bool:
    """Delegation chain as a predicate. _assert_may_manage raises on the same rule."""
    if actor.role == UserRoleEnum.root_admin:
        return True
    if actor.role == UserRoleEnum.instructor:
        return _supervises(actor, target)
    return False


def _assert_may_manage(actor: User, target: User, verb: str) -> None:
    """Delegation chain: TAs manage nobody, instructors manage only the TAs they supervise, root admins manage anyone - but nobody manages themselves."""
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
    if actor.role == UserRoleEnum.instructor and not _supervises(actor, target):
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

    # Read before the change: deleting ends these links.
    leaving_tas = await _supervised_ta_ids(db, current.id) if to_status != UserStatusEnum.active else []

    current.status = to_status

    # Any exit from active must invalidate credentials immediately - a session
    # issued a second before deactivation must not outlive it.
    if to_status != UserStatusEnum.active:
        await _revoke_sessions(db, current.id)

    # A deleted account supervises no one and is supervised by no one
    # (DECISION LOG [0.21.0]). Deactivation keeps its links on purpose, so
    # reactivating restores the same teams.
    if to_status == UserStatusEnum.deleted:
        await _end_links(db, current.id, actor.id)

    # Either way the instructor stops counting, so their TAs may now have no one.
    await _sign_out_unsupervised(db, leaving_tas)

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
    # Root admin only since a TA can be shared, one instructor's deactivate would lock TAs out of every team.
    if actor.role != UserRoleEnum.root_admin:
        logger.warning("Actor %s may not deactivate users.", actor.id)
        raise PermissionError(f"role {actor.role} may not deactivate users")
    target = await _load_manageable(db, user_id)
    _assert_may_manage(actor, target, "deactivate")
    return await _transition(db, actor, target, UserStatusEnum.deactivated, reason)


async def reactivate_user(db: AsyncSession, actor: User, user_id: uuid.UUID, reason: str | None = None) -> User:
    """Restores access to a deactivated user. Cannot reactivate a deleted one."""
    if actor.role != UserRoleEnum.root_admin:
        logger.warning("Actor %s may not reactivate users.", actor.id)
        raise PermissionError(f"role {actor.role} may not reactivate users")
    target = await _load_manageable(db, user_id)
    _assert_may_manage(actor, target, "reactivate")
    return await _transition(db, actor, target, UserStatusEnum.active, reason)


async def resend_invite(db: AsyncSession, actor: User, user_id: uuid.UUID) -> User:
    """Re-sends the Auth0 password-set email to an invitee who has never signed in before."""
    target = await _load_manageable(db, user_id)
    _assert_may_manage(actor, target, "resend an invite to")
    if target.status != UserStatusEnum.active or target.first_login_at is not None:
        raise InvalidStatusTransitionError("Only an active account that has never signed in can be re-invited.")
    await resend_invite_email(target.email)
    logger.info("Invite re-sent to user %s by %s.", target.id, actor.id)
    return target


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


async def change_user_role(db: AsyncSession, actor: User, user_id: uuid.UUID, new_role: UserRoleEnum) -> User:
    """
    Root-admin-only role reassignment, isolated from provisioning
    (`create_user`) so a role change is always its own distinct, audited
    action (`user_role_events`, mirroring `user_status_events`).

    `root_admin` is never a valid target, in either direction - the route's
    request schema already excludes it as the new role, so only the existing
    role needs checking here.
    """
    target = await _load_manageable(db, user_id)
    if target.role == UserRoleEnum.root_admin:
        logger.warning("Actor %s attempted to change a root_admin's role.", actor.id)
        raise PermissionError("root_admin accounts cannot have their role changed")

    from_role = target.role
    target.role = new_role
    # A link means instructor-supervises-TA; neither end survives a role swap.
    if from_role != new_role:
        leaving_tas = await _supervised_ta_ids(db, target.id)
        await _end_links(db, target.id, actor.id)
        await _sign_out_unsupervised(db, leaving_tas)
    db.add(UserRoleEvent(user_id=target.id, actor_id=actor.id, from_role=from_role, to_role=new_role))
    await db.commit()
    await db.refresh(target)
    logger.info("User %s role changed %s -> %s by %s.", target.id, from_role.value, new_role.value, actor.id)
    return target


async def update_display_name(db: AsyncSession, actor: User, user_id: uuid.UUID, display_name: str) -> User:
    """Can only be used by yourself or root_admin. Anyone else gets
    UserNotFoundError."""
    if actor.role != UserRoleEnum.root_admin and actor.id != user_id:
        raise UserNotFoundError(str(user_id))

    target = await _load_manageable(db, user_id)
    if target.status == UserStatusEnum.deleted:
        raise InvalidStatusTransitionError("a deleted account cannot be renamed")

    target.display_name = display_name
    await db.commit()
    await db.refresh(target)
    logger.info("User %s renamed by %s.", target.id, actor.id)
    return target


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
        return _supervises(actor, target)
    if actor.role == UserRoleEnum.teaching_assistant:
        # TAs only see their own supervisors.
        return target.id in actor.supervisor_ids
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


async def _link(db: AsyncSession, actor: User, ta: User, instructor_id: uuid.UUID) -> None:
    """Adds an active link unless the pair already has one, commits, and
    reloads `ta.supervisors` so the caller returns a current row."""
    existing = await db.execute(
        select(Supervision.id).where(
            Supervision.ta_id == ta.id,
            Supervision.instructor_id == instructor_id,
            Supervision.ended_at.is_(None),
        )
    )
    if existing.first() is None:
        db.add(Supervision(ta_id=ta.id, instructor_id=instructor_id, created_by=actor.id))
        try:
            await db.commit()
        except IntegrityError:
            # A concurrent request linked the same pair first; the partial
            # unique index kept exactly one. Same outcome as ours.
            await db.rollback()
    await db.refresh(ta)


async def link_supervisor(db: AsyncSession, actor: User, ta_id: uuid.UUID, instructor_id: uuid.UUID) -> User:
    """root_admin places a teaching assistant on an instructor's team.

    This operation is additive, other supervisors are kept. An existing link is a no-op.
    Instructors add TAs to themsleves by calling the add_teaching_assistant function.
    """
    if actor.role != UserRoleEnum.root_admin:
        logger.warning("Actor %s may not place assistants.", actor.id)
        raise PermissionError(f"role {actor.role} may not place assistants")

    target = await _load_manageable(db, ta_id)
    if target.role != UserRoleEnum.teaching_assistant:
        raise InvalidSupervisorError("only a teaching assistant has a supervisor")
    if target.status != UserStatusEnum.active:
        raise InvalidStatusTransitionError("only an active teaching assistant can be placed")
    await _assert_supervisor_available(db, instructor_id)

    await _link(db, actor, target, instructor_id)
    logger.info("Assistant %s linked to instructor %s by %s.", target.id, instructor_id, actor.id)
    return target


async def end_supervision(db: AsyncSession, actor: User, ta_id: uuid.UUID, instructor_id: uuid.UUID) -> User:
    """Ends one instructor's supervision of a TA ("Remove from team").

    root_admin may end any link but an instructor can only end their own.
    Every refusal is a UserNotFoundError to prevent enumeration of team structure.
    Ending the TA's last active link signs them out in the same commit (DECISION LOG [0.22.0]).
    """
    if actor.role != UserRoleEnum.root_admin and actor.id != instructor_id:
        raise UserNotFoundError(str(ta_id))

    result = await db.execute(
        select(Supervision).where(
            Supervision.ta_id == ta_id,
            Supervision.instructor_id == instructor_id,
            Supervision.ended_at.is_(None),
        )
    )
    link = result.scalar_one_or_none()
    if link is None:
        raise UserNotFoundError(str(ta_id))

    link.ended_at = datetime.now(UTC)
    link.ended_by = actor.id
    await _sign_out_unsupervised(db, [ta_id])

    target = await _load_manageable(db, ta_id)
    await db.refresh(target)
    await db.commit()
    logger.info("Supervision of %s by %s ended by %s.", target.id, instructor_id, actor.id)
    return target


async def _rows_for_email(db: AsyncSession, email: str) -> list[User]:
    """Every row for this (normalised) email, most recent first. Deleted rows
    are kept for attribution, so there can be several."""
    result = await db.execute(select(User).where(User.email == email).order_by(User.created_at.desc()))
    return list(result.scalars().all())


async def _provision(
    db: AsyncSession,
    actor: User,
    email: str,
    role: UserRoleEnum,
    reusable: User | None,
    supervisor_id: uuid.UUID | None = None,
) -> User:
    """Creates the Auth0 credential and the local row together, plus an
    optional supervision link, in one commit.

    Auth0 emails the invitee their own password-set link; Disable Sign Ups
    means that is the only way they get a credential. A local row without a
    credential is a permanent lockout, so a failed commit removes the
    credential again.
    """
    # A stale Auth0 credential is never adopted. Instead, a new invite will replace the account.
    # Prevents old credentials from being used to sign in to a new account.
    stale_auth0_id = await find_auth0_user_id_by_email(email)
    if stale_auth0_id is not None:
        logger.warning("Auth0 already has a credential for %s with no live user - replacing it.", email)
        if not await delete_auth0_user(stale_auth0_id):
            raise Auth0ProvisioningError(f"Could not remove the stale Auth0 credential for {email}")

    auth0_user_id = await invite_user(email)

    if reusable is not None:
        # Re-using a deleted row: the address may now belong to someone else, so
        # nothing personal carries over. provisioned_by records this invite.
        reusable.role = role
        reusable.display_name = None
        reusable.provisioned_by = actor.id
        reusable.auth0_sub = auth0_user_id
        reusable.status = UserStatusEnum.active
        reusable.first_login_at = None
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
        user = User(id=uuid.uuid4(), email=email, role=role, provisioned_by=actor.id, auth0_sub=auth0_user_id)
        db.add(user)

    try:
        if supervisor_id is not None:
            # Flush the user first: no ORM relationship orders the two inserts,
            # and the link's FK needs the row. Same transaction, so still atomic.
            await db.flush()
            db.add(Supervision(ta_id=user.id, instructor_id=supervisor_id, created_by=actor.id))
        await db.commit()
    except Exception:
        # Roll back the Auth0 credential too, or the email is stuck.
        await db.rollback()
        await delete_auth0_user(auth0_user_id)
        raise
    await db.refresh(user)
    logger.info("User %s provisioned as %s by %s.", user.id, role.value, actor.id)
    return user


async def create_user(
    db: AsyncSession,
    actor: User,
    email: str,
    role: UserRoleEnum,
    supervisor_id: uuid.UUID | None = None,
) -> User:
    """root_admin provisioning (POST /api/users). Instructors add TAs through
    add_teaching_assistant instead.

    A deleted email is re-provisioned by re-using its row, so deleting someone
    never makes them unprovisionable. An optional supervisor is linked in the
    same commit as the account and the invite; everything is validated before
    Auth0 is called, so a refusal leaves nothing to clean up.
    """
    if actor.role != UserRoleEnum.root_admin:
        logger.warning("Actor %s with role %s may not provision users.", actor.id, actor.role)
        raise PermissionError(f"role {actor.role} may not provision users")
    if role == UserRoleEnum.root_admin:
        logger.warning("Actor %s attempted to provision a root_admin user, always rejected.", actor.id)
        raise PermissionError("root_admin cannot be provisioned via this endpoint")

    if supervisor_id is not None:
        if role != UserRoleEnum.teaching_assistant:
            raise InvalidSupervisorError("only a teaching assistant has a supervisor")
        await _assert_supervisor_available(db, supervisor_id)

    email = normalize_email(email)
    rows = await _rows_for_email(db, email)
    if any(row.status != UserStatusEnum.deleted for row in rows):
        logger.warning("Attempted to provision duplicate email: %s", email)
        raise EmailAlreadyExistsError(email)

    return await _provision(db, actor, email, role, rows[0] if rows else None, supervisor_id)


async def add_teaching_assistant(db: AsyncSession, actor: User, email: str) -> User:
    """
    Used by instructors to add a TA to their own team.

    The whole process is atomic: provision email, invitiation and linking to the instructor.

    TODO(notifications): linking a TA who already has supervisors should notify
    them and root_admin. Deferred until a notification system exists.
    """
    # Gated only for instructors.
    if actor.role != UserRoleEnum.instructor:
        logger.warning("Actor %s with role %s may not add teaching assistants.", actor.id, actor.role)
        raise PermissionError(f"role {actor.role} may not add teaching assistants")

    email = normalize_email(email)
    rows = await _rows_for_email(db, email)
    live = next((row for row in rows if row.status != UserStatusEnum.deleted), None)

    # If the email does not exist, provision a new TA and link them to the instructor.
    if not rows:
        return await _provision(db, actor, email, UserRoleEnum.teaching_assistant, None, supervisor_id=actor.id)

    if live is None:
        # Deleted accounts cannot be re-used by instructors.
        reason = "only deleted accounts use it"
    elif live.role != UserRoleEnum.teaching_assistant:
        # Only can assign TAs to instructors.
        reason = f"it belongs to a {live.role.value}"
    elif live.status != UserStatusEnum.active:
        # Deactivated account must be reactivated by root_admin first
        reason = f"the account is {live.status.value}"
    else:
        await _link(db, actor, live, actor.id)
        logger.info("Instructor %s added assistant %s to their team.", actor.id, live.id)
        return live

    logger.info("Refused to add %s to instructor %s's team: %s.", email, actor.id, reason)
    raise CannotAddTeachingAssistantError(reason)


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
        if role is not None and role != UserRoleEnum.teaching_assistant:
            logger.warning("Actor %s may not list role %s.", actor.id, role)
            raise PermissionError(f"role {actor.role} may not list role {role}")
        # The TA that they currently supervise, found from the Supervision table
        supervised = select(Supervision.ta_id).where(
            Supervision.instructor_id == actor.id, Supervision.ended_at.is_(None)
        )
        query = query.where(User.role == UserRoleEnum.teaching_assistant, User.id.in_(supervised))
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
