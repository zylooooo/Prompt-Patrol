import logging
import uuid

import pytest
from sqlalchemy import select

from exceptions import (
    EmailAlreadyExistsError,
    InvalidStatusTransitionError,
    InvalidSupervisorError,
    UserNotFoundError,
)
from models import User, UserRoleEnum, UserStatusEnum, UserStatusEvent
from services.users_service import (
    LoginRejection,
    _can_view_user,
    _may_manage,
    create_user,
    deactivate_user,
    delete_user,
    get_user_by_id,
    list_users,
    normalize_email,
    reactivate_user,
    resolve_or_bind_user,
    set_supervisor,
)


def _user(role, provisioned_by=None, email=None, status=UserStatusEnum.active):
    uid = uuid.uuid4()
    return User(
        id=uid,
        email=email or f"{role.value}-{uid}@smu.edu.sg",
        role=role,
        provisioned_by=provisioned_by,
        status=status,
    )


def _deactivated_user(role, provisioned_by=None, email=None):
    return _user(role, provisioned_by=provisioned_by, email=email, status=UserStatusEnum.deactivated)


def _deleted_user(role, provisioned_by=None, email=None):
    return _user(role, provisioned_by=provisioned_by, email=email, status=UserStatusEnum.deleted)


def test_root_admin_sees_everyone():
    admin = _user(UserRoleEnum.root_admin)
    other_admin = _user(UserRoleEnum.root_admin)
    assert _can_view_user(admin, other_admin) is True


def test_everyone_sees_themselves():
    ta = _user(UserRoleEnum.teaching_assistant)
    assert _can_view_user(ta, ta) is True


def test_root_admin_invisible_to_non_admin():
    instructor = _user(UserRoleEnum.instructor)
    admin = _user(UserRoleEnum.root_admin)
    assert _can_view_user(instructor, admin) is False


def test_instructor_sees_only_their_own_assistants():
    """Narrowed 2026-08-18 to the delegation chain. This used to allow any
    instructor and any TA, which contradicted what list_users returned for the
    same actor - two answers to one question, and the wider one was reachable
    through GET /api/users/{id}."""
    instructor = _user(UserRoleEnum.instructor)
    other_instructor = _user(UserRoleEnum.instructor)
    own_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    other_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=other_instructor.id)

    assert _can_view_user(instructor, own_ta) is True
    assert _can_view_user(instructor, other_ta) is False
    assert _can_view_user(instructor, other_instructor) is False


def test_ta_sees_only_their_own_supervisor():
    instructor = _user(UserRoleEnum.instructor)
    other_instructor = _user(UserRoleEnum.instructor)
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)

    assert _can_view_user(ta, instructor) is True
    assert _can_view_user(ta, other_instructor) is False


def test_ta_sees_no_other_assistants():
    instructor_id = uuid.uuid4()
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor_id)
    sibling_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor_id)
    unrelated_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=uuid.uuid4())

    assert _can_view_user(ta, sibling_ta) is False
    assert _can_view_user(ta, unrelated_ta) is False


def test_cli_provisioned_accounts_are_not_siblings():
    """scripts/provision_user leaves provisioned_by NULL, and NULL == NULL is
    True in Python, so the old provisioned_by-to-provisioned_by comparison let
    every seeded account read every other one. This pins the property, so
    reintroducing that comparison fails here."""
    a = _user(UserRoleEnum.teaching_assistant, provisioned_by=None)
    b = _user(UserRoleEnum.teaching_assistant, provisioned_by=None)
    instructor = _user(UserRoleEnum.instructor, provisioned_by=None)

    assert _can_view_user(a, b) is False
    assert _can_view_user(a, instructor) is False


@pytest.mark.asyncio
async def test_resolve_by_oid_when_already_bound(db_session):
    user = User(id=uuid.uuid4(), email="a@smu.edu.sg", entra_oid="oid-1", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="oid-1", email="different@smu.edu.sg")
    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_binds_oid_on_first_login_via_email_fallback(db_session):
    user = User(id=uuid.uuid4(), email="a@smu.edu.sg", entra_oid=None, role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="oid-new", email="a@smu.edu.sg")
    assert resolved.id == user.id
    assert resolved.entra_oid == "oid-new"


@pytest.mark.asyncio
async def test_oid_match_wins_over_conflicting_email_match(db_session):
    # Two distinct rows: one matches by entra_oid, a *different* row would
    # match by email if email were checked first. oid lookup must win and
    # the email-matching row must be left untouched.
    oid_user = User(id=uuid.uuid4(), email="oid-owner@smu.edu.sg", entra_oid="oid-shared", role=UserRoleEnum.instructor)
    email_user = User(id=uuid.uuid4(), email="conflict@smu.edu.sg", entra_oid=None, role=UserRoleEnum.instructor)
    db_session.add_all([oid_user, email_user])
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="oid-shared", email="conflict@smu.edu.sg")

    assert resolved.id == oid_user.id
    await db_session.refresh(email_user)
    assert email_user.entra_oid is None


@pytest.mark.asyncio
async def test_email_fallback_does_not_rebind_an_already_bound_row(db_session):
    # S0. The email claim is mutable and unverified, so it may claim an unbound
    # row once and never move one that already belongs to an identity. Before
    # the fix this returned the victim's row and the callback minted a session
    # on it, handing over the account and its role.
    victim = User(id=uuid.uuid4(), email="victim@smu.edu.sg", entra_oid="victim-oid", role=UserRoleEnum.root_admin)
    db_session.add(victim)
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="attacker-oid", email="victim@smu.edu.sg")

    assert isinstance(resolved, LoginRejection)
    await db_session.refresh(victim)
    assert victim.entra_oid == "victim-oid"


@pytest.mark.asyncio
async def test_owner_still_resolves_after_a_rejected_takeover(db_session):
    # The rejection must not disturb the row: the real owner signs in as normal.
    victim = User(id=uuid.uuid4(), email="victim@smu.edu.sg", entra_oid="victim-oid", role=UserRoleEnum.instructor)
    db_session.add(victim)
    await db_session.commit()

    await resolve_or_bind_user(db_session, oid="attacker-oid", email="victim@smu.edu.sg")
    resolved = await resolve_or_bind_user(db_session, oid="victim-oid", email="victim@smu.edu.sg")

    assert resolved is not None
    assert resolved.id == victim.id


@pytest.mark.asyncio
async def test_rejected_takeover_is_indistinguishable_from_unprovisioned(db_session):
    # Both denials return the same value, so the caller cannot use the response
    # to discover whether an address is provisioned.
    bound = User(id=uuid.uuid4(), email="bound@smu.edu.sg", entra_oid="someone-oid", role=UserRoleEnum.instructor)
    db_session.add(bound)
    await db_session.commit()

    takeover = await resolve_or_bind_user(db_session, oid="attacker-oid", email="bound@smu.edu.sg")
    unknown = await resolve_or_bind_user(db_session, oid="attacker-oid", email="nobody@smu.edu.sg")

    assert isinstance(takeover, LoginRejection) and isinstance(unknown, LoginRejection)


@pytest.mark.asyncio
async def test_rejected_takeover_is_logged_as_a_security_event(db_session, caplog):
    bound = User(id=uuid.uuid4(), email="bound@smu.edu.sg", entra_oid="someone-oid", role=UserRoleEnum.instructor)
    db_session.add(bound)
    await db_session.commit()

    with caplog.at_level(logging.WARNING, logger="services.users_service"):
        await resolve_or_bind_user(db_session, oid="attacker-oid", email="bound@smu.edu.sg")

    assert any("already bound" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_unknown_email_is_not_logged_as_a_takeover(db_session, caplog):
    # A routine miss is not a security event; only a collision with a bound row is.
    with caplog.at_level(logging.WARNING, logger="services.users_service"):
        await resolve_or_bind_user(db_session, oid="oid-x", email="nobody@smu.edu.sg")

    assert caplog.records == []


@pytest.mark.asyncio
async def test_an_oid_held_by_a_deactivated_account_fails_closed(db_session):
    # A deactivated user is still one of ours, so their Entra identity stays
    # reserved. Binding it to a second row would split one person across two.
    off = _deactivated_user(UserRoleEnum.instructor, email="old@smu.edu.sg")
    off.entra_oid = "held-oid"
    unbound = _user(UserRoleEnum.instructor, email="new@smu.edu.sg")
    unbound.entra_oid = None
    await _seed(db_session, off, unbound)

    resolved = await resolve_or_bind_user(db_session, oid="held-oid", email="new@smu.edu.sg")

    assert isinstance(resolved, LoginRejection)
    await db_session.refresh(unbound)
    assert unbound.entra_oid is None


@pytest.mark.asyncio
async def test_an_oid_held_by_a_deleted_account_is_free_to_rebind(db_session):
    # The counterpart: deletion releases the identity so the same person can be
    # provisioned fresh and sign in normally.
    gone = _deleted_user(UserRoleEnum.instructor, email="old@smu.edu.sg")
    gone.entra_oid = "released-oid"
    fresh = _user(UserRoleEnum.instructor, email="new@smu.edu.sg")
    fresh.entra_oid = None
    await _seed(db_session, gone, fresh)

    resolved = await resolve_or_bind_user(db_session, oid="released-oid", email="new@smu.edu.sg")

    assert not isinstance(resolved, LoginRejection)
    assert resolved.id == fresh.id
    assert resolved.entra_oid == "released-oid"


@pytest.mark.asyncio
async def test_unprovisioned_email_returns_none(db_session):
    resolved = await resolve_or_bind_user(db_session, oid="oid-x", email="nobody@smu.edu.sg")
    assert isinstance(resolved, LoginRejection)


@pytest.mark.asyncio
async def test_deleted_user_not_resolved(db_session):
    user = _deleted_user(UserRoleEnum.instructor, email="gone@smu.edu.sg")
    user.entra_oid = "oid-gone"
    db_session.add(user)
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="oid-gone", email="gone@smu.edu.sg")
    assert isinstance(resolved, LoginRejection)


@pytest.mark.asyncio
async def test_root_admin_creates_instructor(db_session):
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    created = await create_user(db_session, admin, "new-instructor@smu.edu.sg", UserRoleEnum.instructor)

    assert created.email == "new-instructor@smu.edu.sg"
    assert created.role == UserRoleEnum.instructor
    assert created.provisioned_by == admin.id


@pytest.mark.asyncio
async def test_instructor_creates_ta(db_session):
    instructor = _user(UserRoleEnum.instructor)
    db_session.add(instructor)
    await db_session.commit()

    created = await create_user(db_session, instructor, "new-ta@smu.edu.sg", UserRoleEnum.teaching_assistant)

    assert created.role == UserRoleEnum.teaching_assistant
    assert created.provisioned_by == instructor.id


@pytest.mark.asyncio
async def test_ta_cannot_create_any_user(db_session):
    ta = _user(UserRoleEnum.teaching_assistant)
    db_session.add(ta)
    await db_session.commit()

    with pytest.raises(PermissionError):
        await create_user(db_session, ta, "nope@smu.edu.sg", UserRoleEnum.teaching_assistant)


@pytest.mark.asyncio
async def test_instructor_cannot_create_instructor(db_session):
    instructor = _user(UserRoleEnum.instructor)
    db_session.add(instructor)
    await db_session.commit()

    with pytest.raises(PermissionError):
        await create_user(db_session, instructor, "peer@smu.edu.sg", UserRoleEnum.instructor)


@pytest.mark.asyncio
async def test_root_admin_cannot_create_root_admin(db_session):
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    with pytest.raises(PermissionError):
        await create_user(db_session, admin, "another-admin@smu.edu.sg", UserRoleEnum.root_admin)


@pytest.mark.asyncio
async def test_duplicate_email_raises_conflict(db_session):
    admin = _user(UserRoleEnum.root_admin)
    existing = User(id=uuid.uuid4(), email="taken@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add_all([admin, existing])
    await db_session.commit()

    with pytest.raises(EmailAlreadyExistsError):
        await create_user(db_session, admin, "taken@smu.edu.sg", UserRoleEnum.instructor)


@pytest.mark.asyncio
async def test_create_user_persists_row(db_session):
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    created = await create_user(db_session, admin, "persisted@smu.edu.sg", UserRoleEnum.instructor)

    result = await db_session.execute(select(User).where(User.id == created.id))
    assert result.scalar_one_or_none() is not None


# display_name is a label, never an identifier. It has no uniqueness, nothing
# looks a user up by it, and Entra's `name` claim overwrites it on first login.


@pytest.mark.asyncio
async def test_create_user_stores_a_display_name(db_session):
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    created = await create_user(db_session, admin, "named@smu.edu.sg", UserRoleEnum.instructor, "  Amirah Rahman  ")

    assert created.display_name == "Amirah Rahman"


@pytest.mark.asyncio
async def test_create_user_defaults_display_name_to_null(db_session):
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    created = await create_user(db_session, admin, "unnamed@smu.edu.sg", UserRoleEnum.instructor)

    assert created.display_name is None


@pytest.mark.asyncio
async def test_a_blank_display_name_is_stored_as_null(db_session):
    # An empty form field must not become a user whose name renders as "".
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    created = await create_user(db_session, admin, "blank@smu.edu.sg", UserRoleEnum.instructor, "   ")

    assert created.display_name is None


@pytest.mark.asyncio
async def test_display_name_does_not_have_to_be_unique(db_session):
    # Two real people share a name far more often than two email addresses do;
    # the partial unique indexes from 0004 cover email and entra_oid only.
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    first = await create_user(db_session, admin, "wei.1@smu.edu.sg", UserRoleEnum.instructor, "Wei Lin")
    second = await create_user(db_session, admin, "wei.2@smu.edu.sg", UserRoleEnum.instructor, "Wei Lin")

    assert first.display_name == second.display_name == "Wei Lin"
    assert first.id != second.id


@pytest.mark.asyncio
async def test_ta_cannot_list_users(db_session):
    ta = _user(UserRoleEnum.teaching_assistant)
    db_session.add(ta)
    await db_session.commit()

    with pytest.raises(PermissionError):
        await list_users(db_session, ta)


@pytest.mark.asyncio
async def test_root_admin_sees_everyone_in_list(db_session):
    admin = _user(UserRoleEnum.root_admin)
    other_admin = _user(UserRoleEnum.root_admin)
    instructor = _user(UserRoleEnum.instructor)
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    db_session.add_all([admin, other_admin, instructor, ta])
    await db_session.commit()

    items, next_cursor = await list_users(db_session, admin)

    assert {u.id for u in items} == {admin.id, other_admin.id, instructor.id, ta.id}
    assert next_cursor is None


@pytest.mark.asyncio
async def test_instructor_sees_only_own_tas(db_session):
    instructor = _user(UserRoleEnum.instructor)
    other_instructor = _user(UserRoleEnum.instructor)
    db_session.add_all([instructor, other_instructor])
    await db_session.commit()
    own_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    other_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=other_instructor.id)
    db_session.add_all([own_ta, other_ta])
    await db_session.commit()

    items, _ = await list_users(db_session, instructor)

    assert {u.id for u in items} == {own_ta.id}


@pytest.mark.asyncio
async def test_instructor_role_filter_outside_scope_is_refused(db_session):
    """It used to return []. An empty list reads as "there are none" when what
    happened is "you may not ask that" - and the caller cannot tell the two
    apart, so a scoping mistake looks like an empty directory."""
    instructor = _user(UserRoleEnum.instructor)
    db_session.add(instructor)
    await db_session.commit()
    own_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    db_session.add(own_ta)
    await db_session.commit()

    with pytest.raises(PermissionError):
        await list_users(db_session, instructor, role=UserRoleEnum.instructor)

    # The scope itself still works, and asking for it explicitly is allowed.
    items, _ = await list_users(db_session, instructor, role=UserRoleEnum.teaching_assistant)
    assert [u.id for u in items] == [own_ta.id]


@pytest.mark.asyncio
async def test_list_pagination_cursor(db_session):
    admin = _user(UserRoleEnum.root_admin)
    others = [_user(UserRoleEnum.instructor) for _ in range(3)]
    db_session.add_all([admin, *others])
    await db_session.commit()

    first_page, next_cursor = await list_users(db_session, admin, limit=2)
    assert len(first_page) == 2
    assert next_cursor is not None

    second_page, next_cursor2 = await list_users(db_session, admin, limit=2, cursor=next_cursor)
    assert next_cursor2 is None

    seen_ids = {u.id for u in first_page} | {u.id for u in second_page}
    assert seen_ids == {admin.id, others[0].id, others[1].id, others[2].id}
    # No overlap between pages.
    assert {u.id for u in first_page}.isdisjoint({u.id for u in second_page})


@pytest.mark.asyncio
async def test_list_invalid_cursor_raises(db_session):
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    with pytest.raises(ValueError):
        await list_users(db_session, admin, cursor="not-a-valid-cursor!!")


# --- email normalisation ----------------------------------------------------
# The stored form and the matched form must be the same one, or a correctly
# provisioned person is told they are not provisioned.


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ada@smu.edu.sg", "ada@smu.edu.sg"),
        ("ADA@SMU.EDU.SG", "ada@smu.edu.sg"),
        ("  ada@smu.edu.sg  ", "ada@smu.edu.sg"),
        ("\tAda@SMU.edu.sg\n", "ada@smu.edu.sg"),
        ("ada@smu.edu.sg", "ada@smu.edu.sg"),
    ],
)
def test_normalize_email_folds_case_and_trims(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.asyncio
async def test_login_binds_when_entra_sends_a_different_case_than_provisioned(db_session):
    # The reported symptom: provisioned lowercase, Entra sends mixed case, and
    # the user was rejected as unprovisioned with nothing able to explain why.
    user = User(id=uuid.uuid4(), email="ada@smu.edu.sg", entra_oid=None, role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="oid-ada", email="Ada@SMU.edu.sg")

    assert resolved is not None
    assert resolved.id == user.id
    assert resolved.entra_oid == "oid-ada"


@pytest.mark.asyncio
async def test_login_matches_an_already_bound_row_regardless_of_claim_case(db_session):
    user = User(id=uuid.uuid4(), email="ada@smu.edu.sg", entra_oid="oid-ada", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="oid-ada", email="ADA@SMU.EDU.SG")

    assert resolved is not None
    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_login_tolerates_a_padded_email_claim(db_session):
    user = User(id=uuid.uuid4(), email="ada@smu.edu.sg", entra_oid=None, role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="oid-ada", email="  ada@smu.edu.sg  ")

    assert resolved is not None
    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_case_folding_does_not_let_an_email_claim_take_a_bound_row(db_session):
    # The S0 guard must survive normalisation: folding case must not turn a
    # rejected rebind into an accepted one.
    victim = User(id=uuid.uuid4(), email="victim@smu.edu.sg", entra_oid="victim-oid", role=UserRoleEnum.root_admin)
    db_session.add(victim)
    await db_session.commit()

    resolved = await resolve_or_bind_user(db_session, oid="attacker-oid", email="VICTIM@smu.edu.sg")

    assert isinstance(resolved, LoginRejection)
    await db_session.refresh(victim)
    assert victim.entra_oid == "victim-oid"


@pytest.mark.asyncio
async def test_create_user_stores_the_normalised_email(db_session):
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    created = await create_user(db_session, admin, "  New.Person@SMU.edu.sg ", UserRoleEnum.instructor)

    assert created.email == "new.person@smu.edu.sg"


@pytest.mark.asyncio
async def test_create_user_rejects_a_duplicate_differing_only_by_case(db_session):
    # Without normalisation both rows are accepted, and the second one is a
    # second account for the same person that no login will ever reach.
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()
    await create_user(db_session, admin, "person@smu.edu.sg", UserRoleEnum.instructor)

    with pytest.raises(EmailAlreadyExistsError):
        await create_user(db_session, admin, "Person@SMU.edu.sg", UserRoleEnum.instructor)


# ===========================================================================
# Lifecycle: ACTIVE <-> DEACTIVATED -> DELETED (terminal)
# ===========================================================================


async def _seed(db, *users):
    db.add_all(users)
    await db.commit()


async def _events(db, user_id):
    result = await db.execute(select(UserStatusEvent).where(UserStatusEvent.user_id == user_id))
    return list(result.scalars().all())


# --- permitted transitions -------------------------------------------------


@pytest.mark.asyncio
async def test_active_to_deactivated(db_session):
    admin, ta = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)

    result = await deactivate_user(db_session, admin, ta.id, reason="semester ended")

    assert result.status == UserStatusEnum.deactivated


@pytest.mark.asyncio
async def test_deactivated_to_active(db_session):
    admin = _user(UserRoleEnum.root_admin)
    ta = _deactivated_user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)

    result = await reactivate_user(db_session, admin, ta.id)

    assert result.status == UserStatusEnum.active


@pytest.mark.asyncio
async def test_active_to_deleted(db_session):
    admin, ta = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)

    result = await delete_user(db_session, admin, ta.id, reason="left the university")

    assert result.status == UserStatusEnum.deleted


@pytest.mark.asyncio
async def test_deactivated_to_deleted(db_session):
    admin = _user(UserRoleEnum.root_admin)
    ta = _deactivated_user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)

    result = await delete_user(db_session, admin, ta.id)

    assert result.status == UserStatusEnum.deleted


# --- forbidden transitions -------------------------------------------------


@pytest.mark.asyncio
async def test_deleted_is_terminal(db_session):
    # The whole point of the distinction: deletion cannot be walked back. Access
    # is re-granted by provisioning a fresh account, which is visible and audited.
    admin = _user(UserRoleEnum.root_admin)
    ta = _deleted_user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)

    with pytest.raises(InvalidStatusTransitionError):
        await reactivate_user(db_session, admin, ta.id)
    with pytest.raises(InvalidStatusTransitionError):
        await deactivate_user(db_session, admin, ta.id)
    with pytest.raises(InvalidStatusTransitionError):
        await delete_user(db_session, admin, ta.id)


@pytest.mark.asyncio
async def test_cannot_deactivate_an_already_deactivated_user(db_session):
    admin = _user(UserRoleEnum.root_admin)
    ta = _deactivated_user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)

    with pytest.raises(InvalidStatusTransitionError):
        await deactivate_user(db_session, admin, ta.id)


@pytest.mark.asyncio
async def test_cannot_reactivate_an_already_active_user(db_session):
    admin, ta = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)

    with pytest.raises(InvalidStatusTransitionError):
        await reactivate_user(db_session, admin, ta.id)


@pytest.mark.asyncio
async def test_transition_on_unknown_user_raises_not_found(db_session):
    admin = _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin)

    with pytest.raises(UserNotFoundError):
        await deactivate_user(db_session, admin, uuid.uuid4())


# --- credentials die with the status --------------------------------------


@pytest.mark.asyncio
async def test_deactivation_revokes_live_sessions(db_session):
    from auth import SessionFailure
    from services import authenticate_session, create_session

    admin, ta = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)
    token = await create_session(db_session, ta.id)
    assert not isinstance(await authenticate_session(db_session, token), SessionFailure)

    await deactivate_user(db_session, admin, ta.id)

    # Not session_revoked: the account status is the reason the person can act
    # on, and it outranks the revocation it caused.
    assert await authenticate_session(db_session, token) is SessionFailure.account_deactivated


@pytest.mark.asyncio
async def test_deletion_revokes_live_sessions(db_session):
    from auth import SessionFailure
    from services import authenticate_session, create_session

    admin, ta = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)
    token = await create_session(db_session, ta.id)

    await delete_user(db_session, admin, ta.id)

    assert await authenticate_session(db_session, token) is SessionFailure.account_deactivated


@pytest.mark.asyncio
async def test_reactivation_does_not_resurrect_old_sessions(db_session):
    # Revocation is permanent. Coming back means signing in again, not having a
    # token from before the deactivation quietly start working.
    from auth import SessionFailure
    from services import authenticate_session, create_session

    admin, ta = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)
    token = await create_session(db_session, ta.id)
    await deactivate_user(db_session, admin, ta.id)

    await reactivate_user(db_session, admin, ta.id)

    # The account is active again, so the surviving reason is the revocation.
    assert await authenticate_session(db_session, token) is SessionFailure.session_revoked


# --- who may do what -------------------------------------------------------


@pytest.mark.asyncio
async def test_ta_cannot_change_anyone(db_session):
    ta, other = _user(UserRoleEnum.teaching_assistant), _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, ta, other)

    for op in (deactivate_user, reactivate_user, delete_user):
        with pytest.raises(PermissionError):
            await op(db_session, ta, other.id)


@pytest.mark.asyncio
async def test_instructor_may_deactivate_only_their_own_ta(db_session):
    instructor = _user(UserRoleEnum.instructor)
    other_instructor = _user(UserRoleEnum.instructor)
    own = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    other = _user(UserRoleEnum.teaching_assistant, provisioned_by=other_instructor.id)
    await _seed(db_session, instructor, other_instructor, own, other)

    assert (await deactivate_user(db_session, instructor, own.id)).status == UserStatusEnum.deactivated
    with pytest.raises(PermissionError):
        await deactivate_user(db_session, instructor, other.id)


@pytest.mark.asyncio
async def test_deletion_is_root_admin_only(db_session):
    # Deletion is terminal, so it needs a stronger privilege than the reversible
    # deactivation an instructor performs when offboarding their own TA.
    instructor = _user(UserRoleEnum.instructor)
    own = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    await _seed(db_session, instructor, own)

    with pytest.raises(PermissionError):
        await delete_user(db_session, instructor, own.id)


@pytest.mark.asyncio
async def test_a_root_admin_can_never_be_deleted(db_session):
    # Regression for the one-way door: deletion used to be allowed on a root
    # admin while restoration was refused, so deleting one - or yourself - locked
    # the system out with no route back but manual SQL.
    admin, other_admin = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin, other_admin)

    with pytest.raises(PermissionError):
        await delete_user(db_session, admin, other_admin.id)
    with pytest.raises(PermissionError):
        await delete_user(db_session, admin, admin.id)


# --- audit -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_transition_records_who_what_and_why(db_session):
    admin, ta = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)

    await deactivate_user(db_session, admin, ta.id, reason="on leave")
    await reactivate_user(db_session, admin, ta.id, reason="returned")
    await delete_user(db_session, admin, ta.id, reason="graduated")

    events = sorted(await _events(db_session, ta.id), key=lambda e: e.created_at)
    assert [(e.from_status, e.to_status) for e in events] == [
        (UserStatusEnum.active, UserStatusEnum.deactivated),
        (UserStatusEnum.deactivated, UserStatusEnum.active),
        (UserStatusEnum.active, UserStatusEnum.deleted),
    ]
    assert {e.actor_id for e in events} == {admin.id}
    assert [e.reason for e in events] == ["on leave", "returned", "graduated"]


@pytest.mark.asyncio
async def test_a_refused_transition_records_nothing(db_session):
    admin = _user(UserRoleEnum.root_admin)
    ta = _deleted_user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)

    with pytest.raises(InvalidStatusTransitionError):
        await reactivate_user(db_session, admin, ta.id)

    assert await _events(db_session, ta.id) == []


# --- identity reuse --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_deleted_users_email_can_be_provisioned_again(db_session):
    # Deletion is terminal, so the address must be released - otherwise removing
    # someone bars them from ever holding an account again.
    admin = _user(UserRoleEnum.root_admin)
    ta = _user(UserRoleEnum.teaching_assistant, email="returning@smu.edu.sg")
    await _seed(db_session, admin, ta)
    await delete_user(db_session, admin, ta.id)

    fresh = await create_user(db_session, admin, "returning@smu.edu.sg", UserRoleEnum.instructor)

    assert fresh.id != ta.id
    assert fresh.status == UserStatusEnum.active


@pytest.mark.asyncio
async def test_a_deactivated_users_email_is_still_reserved(db_session):
    # They are still one of ours. Reactivate them rather than creating a second
    # record for the same person.
    admin = _user(UserRoleEnum.root_admin)
    ta = _deactivated_user(UserRoleEnum.teaching_assistant, email="onleave@smu.edu.sg")
    await _seed(db_session, admin, ta)

    with pytest.raises(EmailAlreadyExistsError):
        await create_user(db_session, admin, "onleave@smu.edu.sg", UserRoleEnum.teaching_assistant)


# --- login rejection reasons ----------------------------------------------


@pytest.mark.asyncio
async def test_login_tells_deactivated_and_deleted_apart(db_session):
    deactivated = _deactivated_user(UserRoleEnum.instructor, email="off@smu.edu.sg")
    deleted = _deleted_user(UserRoleEnum.instructor, email="gone@smu.edu.sg")
    await _seed(db_session, deactivated, deleted)

    assert await resolve_or_bind_user(db_session, oid="o1", email="off@smu.edu.sg") is LoginRejection.deactivated
    assert await resolve_or_bind_user(db_session, oid="o2", email="gone@smu.edu.sg") is LoginRejection.deleted
    assert await resolve_or_bind_user(db_session, oid="o3", email="nobody@smu.edu.sg") is LoginRejection.not_provisioned


# --- query defaults --------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_only_active_users_by_default(db_session):
    admin = _user(UserRoleEnum.root_admin)
    active = _user(UserRoleEnum.instructor)
    off = _deactivated_user(UserRoleEnum.instructor)
    gone = _deleted_user(UserRoleEnum.instructor)
    await _seed(db_session, admin, active, off, gone)

    rows, _ = await list_users(db_session, admin)

    assert {u.id for u in rows} == {admin.id, active.id}


@pytest.mark.asyncio
async def test_list_can_be_widened_to_named_statuses(db_session):
    admin = _user(UserRoleEnum.root_admin)
    off = _deactivated_user(UserRoleEnum.instructor)
    gone = _deleted_user(UserRoleEnum.instructor)
    await _seed(db_session, admin, off, gone)

    rows, _ = await list_users(db_session, admin, statuses=frozenset({UserStatusEnum.deactivated}))
    assert {u.id for u in rows} == {off.id}

    rows, _ = await list_users(db_session, admin, statuses=frozenset({UserStatusEnum.active, UserStatusEnum.deleted}))
    assert {u.id for u in rows} == {admin.id, gone.id}


# --- hardening found during re-verification ---------------------------------


@pytest.mark.asyncio
async def test_transition_reads_status_under_the_lock_not_from_a_stale_object(db_session):
    # The guard used to compare a value read before the lock against the same
    # Python object read after it - SQLAlchemy's identity map returns the very
    # same instance, so the comparison could never fail and a racing second
    # request would act on stale state. The locked read now uses
    # populate_existing, so it reflects what is actually committed.
    admin, ta = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)
    await deactivate_user(db_session, admin, ta.id)

    with pytest.raises(InvalidStatusTransitionError):
        await deactivate_user(db_session, admin, ta.id)


@pytest.mark.asyncio
async def test_an_admin_can_open_a_deactivated_user_they_manage(db_session):
    # Needed to reactivate them. Filtering the fetch to active-only made the
    # record a 404 the moment it was deactivated.
    admin = _user(UserRoleEnum.root_admin)
    off = _deactivated_user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, off)

    assert (await get_user_by_id(db_session, admin, off.id)) is not None


@pytest.mark.asyncio
async def test_a_deactivated_user_is_hidden_from_someone_who_cannot_manage_them(db_session):
    # Same None as a missing row, so an ordinary user cannot tell "never
    # existed" from "was removed".
    ta = _user(UserRoleEnum.teaching_assistant)
    off = _deactivated_user(UserRoleEnum.instructor)
    await _seed(db_session, ta, off)

    assert (await get_user_by_id(db_session, ta, off.id)) is None


@pytest.mark.asyncio
async def test_an_instructor_can_open_their_own_deactivated_ta(db_session):
    instructor = _user(UserRoleEnum.instructor)
    other_instructor = _user(UserRoleEnum.instructor)
    own = _deactivated_user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    other = _deactivated_user(UserRoleEnum.teaching_assistant, provisioned_by=other_instructor.id)
    await _seed(db_session, instructor, other_instructor, own, other)

    assert (await get_user_by_id(db_session, instructor, own.id)) is not None
    assert (await get_user_by_id(db_session, instructor, other.id)) is None


@pytest.mark.asyncio
async def test_a_deleted_user_is_never_visible_to_a_non_manager(db_session):
    ta = _user(UserRoleEnum.teaching_assistant)
    gone = _deleted_user(UserRoleEnum.instructor)
    await _seed(db_session, ta, gone)

    assert (await get_user_by_id(db_session, ta, gone.id)) is None


@pytest.mark.asyncio
async def test_a_newly_created_user_starts_active(db_session):
    admin = _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin)

    created = await create_user(db_session, admin, "brand.new@smu.edu.sg", UserRoleEnum.instructor)

    assert created.status == UserStatusEnum.active


@pytest.mark.asyncio
async def test_nobody_can_change_their_own_status(db_session):
    # A root admin deactivating themselves loses their sessions instantly and
    # cannot sign back in, and instructors can only manage their own TAs - so
    # with one root admin there is no route back but manual SQL. Same one-way
    # door that deletion used to be, reached through a different door.
    admin = _user(UserRoleEnum.root_admin)
    instructor = _user(UserRoleEnum.instructor)
    await _seed(db_session, admin, instructor)

    with pytest.raises(PermissionError):
        await deactivate_user(db_session, admin, admin.id)
    with pytest.raises(PermissionError):
        await delete_user(db_session, admin, admin.id)
    with pytest.raises(PermissionError):
        await deactivate_user(db_session, instructor, instructor.id)

    await db_session.refresh(admin)
    assert admin.status == UserStatusEnum.active


# --- who supervises whom ---------------------------------------------------
# `provisioned_by` is the whole supervision model: one instructor per assistant,
# and the SPA gates screening on it. Before this, it always held whoever ran the
# create call, so an admin adding an assistant "under instructor A" produced a
# row supervised by the admin, and the chosen instructor existed only in that
# browser's localStorage.


@pytest.mark.asyncio
async def test_admin_can_name_the_supervising_instructor(db_session):
    admin, instructor = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.instructor)
    await _seed(db_session, admin, instructor)

    created = await create_user(
        db_session, admin, "placed@smu.edu.sg", UserRoleEnum.teaching_assistant, supervisor_id=instructor.id
    )

    assert created.provisioned_by == instructor.id


@pytest.mark.asyncio
async def test_an_admin_created_assistant_with_no_instructor_is_unassigned(db_session):
    # Not the admin's id. The column means "supervisor" for an assistant, and an
    # admin does not supervise - leaving it NULL is what makes the roster's
    # Unassigned filter and the screening gate tell the truth.
    admin = _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin)

    created = await create_user(db_session, admin, "floating@smu.edu.sg", UserRoleEnum.teaching_assistant)

    assert created.provisioned_by is None


@pytest.mark.asyncio
async def test_an_instructor_still_supervises_whoever_they_create(db_session):
    instructor = _user(UserRoleEnum.instructor)
    await _seed(db_session, instructor)

    created = await create_user(db_session, instructor, "mine@smu.edu.sg", UserRoleEnum.teaching_assistant)

    assert created.provisioned_by == instructor.id


@pytest.mark.asyncio
async def test_an_instructor_may_not_place_an_assistant_under_a_colleague(db_session):
    # provisioned_by is what grants management of the row, so this would be
    # handing away access they could not take back.
    instructor, colleague = _user(UserRoleEnum.instructor), _user(UserRoleEnum.instructor)
    await _seed(db_session, instructor, colleague)

    with pytest.raises(PermissionError):
        await create_user(
            db_session, instructor, "theirs@smu.edu.sg", UserRoleEnum.teaching_assistant, supervisor_id=colleague.id
        )


@pytest.mark.asyncio
async def test_an_instructor_naming_themselves_is_accepted(db_session):
    instructor = _user(UserRoleEnum.instructor)
    await _seed(db_session, instructor)

    created = await create_user(
        db_session, instructor, "explicit@smu.edu.sg", UserRoleEnum.teaching_assistant, supervisor_id=instructor.id
    )

    assert created.provisioned_by == instructor.id


@pytest.mark.asyncio
async def test_a_supervisor_must_be_an_instructor(db_session):
    admin, ta = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)

    with pytest.raises(InvalidSupervisorError):
        await create_user(db_session, admin, "nested@smu.edu.sg", UserRoleEnum.teaching_assistant, supervisor_id=ta.id)


@pytest.mark.asyncio
async def test_a_supervisor_must_be_active(db_session):
    admin = _user(UserRoleEnum.root_admin)
    gone = _deactivated_user(UserRoleEnum.instructor)
    await _seed(db_session, admin, gone)

    with pytest.raises(InvalidSupervisorError):
        await create_user(
            db_session, admin, "stranded@smu.edu.sg", UserRoleEnum.teaching_assistant, supervisor_id=gone.id
        )


@pytest.mark.asyncio
async def test_a_supervisor_must_exist(db_session):
    admin = _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin)

    with pytest.raises(InvalidSupervisorError):
        await create_user(
            db_session, admin, "ghost@smu.edu.sg", UserRoleEnum.teaching_assistant, supervisor_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_only_an_assistant_can_be_given_a_supervisor(db_session):
    admin, instructor = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.instructor)
    await _seed(db_session, admin, instructor)

    with pytest.raises(InvalidSupervisorError):
        await create_user(db_session, admin, "peer@smu.edu.sg", UserRoleEnum.instructor, supervisor_id=instructor.id)


@pytest.mark.asyncio
async def test_creating_an_instructor_still_records_its_creator(db_session):
    # For a non-assistant the column keeps its older, purely descriptive meaning.
    admin = _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin)

    created = await create_user(db_session, admin, "prof@smu.edu.sg", UserRoleEnum.instructor)

    assert created.provisioned_by == admin.id


# --- moving an assistant ---------------------------------------------------


@pytest.mark.asyncio
async def test_admin_moves_an_assistant_to_another_instructor(db_session):
    admin, first, second = (
        _user(UserRoleEnum.root_admin),
        _user(UserRoleEnum.instructor),
        _user(UserRoleEnum.instructor),
    )
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=first.id)
    await _seed(db_session, admin, first, second, ta)

    moved = await set_supervisor(db_session, admin, ta.id, second.id)

    assert moved.provisioned_by == second.id


@pytest.mark.asyncio
async def test_the_new_instructor_can_manage_a_moved_assistant(db_session):
    # The point of the move: management follows the column, so this is what the
    # reassignment actually buys.
    admin, first, second = (
        _user(UserRoleEnum.root_admin),
        _user(UserRoleEnum.instructor),
        _user(UserRoleEnum.instructor),
    )
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=first.id)
    await _seed(db_session, admin, first, second, ta)

    moved = await set_supervisor(db_session, admin, ta.id, second.id)

    assert _may_manage(second, moved) is True
    assert _may_manage(first, moved) is False


@pytest.mark.asyncio
async def test_a_null_supervisor_unassigns_the_assistant(db_session):
    admin, instructor = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.instructor)
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    await _seed(db_session, admin, instructor, ta)

    unassigned = await set_supervisor(db_session, admin, ta.id, None)

    assert unassigned.provisioned_by is None


@pytest.mark.asyncio
async def test_unassigning_revokes_live_sessions(db_session):
    # The SPA decides "may this person screen?" from the session payload it is
    # already holding, so an assistant who kept a session would keep screening
    # until they happened to reload.
    from auth import SessionFailure
    from services import authenticate_session, create_session

    admin, instructor = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.instructor)
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    await _seed(db_session, admin, instructor, ta)
    token = await create_session(db_session, ta.id)
    assert not isinstance(await authenticate_session(db_session, token), SessionFailure)

    await set_supervisor(db_session, admin, ta.id, None)

    assert await authenticate_session(db_session, token) is SessionFailure.session_revoked


@pytest.mark.asyncio
async def test_moving_an_assistant_keeps_them_signed_in(db_session):
    # They still have a supervisor, so nothing they can do has changed.
    from auth import SessionFailure
    from services import authenticate_session, create_session

    admin, first, second = (
        _user(UserRoleEnum.root_admin),
        _user(UserRoleEnum.instructor),
        _user(UserRoleEnum.instructor),
    )
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=first.id)
    await _seed(db_session, admin, first, second, ta)
    token = await create_session(db_session, ta.id)

    await set_supervisor(db_session, admin, ta.id, second.id)

    assert not isinstance(await authenticate_session(db_session, token), SessionFailure)


@pytest.mark.asyncio
async def test_an_instructor_cannot_reassign_anyone(db_session):
    instructor, colleague = _user(UserRoleEnum.instructor), _user(UserRoleEnum.instructor)
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    await _seed(db_session, instructor, colleague, ta)

    with pytest.raises(PermissionError):
        await set_supervisor(db_session, instructor, ta.id, colleague.id)


@pytest.mark.asyncio
async def test_an_assistant_cannot_reassign_themselves(db_session):
    instructor = _user(UserRoleEnum.instructor)
    ta = _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, instructor, ta)

    with pytest.raises(PermissionError):
        await set_supervisor(db_session, ta, ta.id, instructor.id)


@pytest.mark.asyncio
async def test_only_an_assistant_can_be_reassigned(db_session):
    admin, instructor, other = (
        _user(UserRoleEnum.root_admin),
        _user(UserRoleEnum.instructor),
        _user(UserRoleEnum.instructor),
    )
    await _seed(db_session, admin, instructor, other)

    with pytest.raises(InvalidSupervisorError):
        await set_supervisor(db_session, admin, instructor.id, other.id)


@pytest.mark.asyncio
async def test_a_deleted_assistant_cannot_be_reassigned(db_session):
    admin, instructor = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.instructor)
    ta = _deleted_user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, instructor, ta)

    with pytest.raises(InvalidStatusTransitionError):
        await set_supervisor(db_session, admin, ta.id, instructor.id)


@pytest.mark.asyncio
async def test_a_deactivated_assistant_can_still_be_reassigned(db_session):
    # Deactivation is reversible, so the roster has to be able to place them
    # before they come back.
    admin, instructor = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.instructor)
    ta = _deactivated_user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, instructor, ta)

    moved = await set_supervisor(db_session, admin, ta.id, instructor.id)

    assert moved.provisioned_by == instructor.id


@pytest.mark.asyncio
async def test_reassigning_an_unknown_user_is_not_found(db_session):
    admin = _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin)

    with pytest.raises(UserNotFoundError):
        await set_supervisor(db_session, admin, uuid.uuid4(), None)


@pytest.mark.asyncio
async def test_an_instructor_may_release_their_own_assistant(db_session):
    # The "Remove" button on the instructor's own page. Releasing is safe because
    # it only ever gives access away, never takes it.
    instructor = _user(UserRoleEnum.instructor)
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    await _seed(db_session, instructor, ta)

    released = await set_supervisor(db_session, instructor, ta.id, None)

    assert released.provisioned_by is None


@pytest.mark.asyncio
async def test_an_instructor_may_not_release_someone_elses_assistant(db_session):
    instructor, colleague = _user(UserRoleEnum.instructor), _user(UserRoleEnum.instructor)
    ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=colleague.id)
    await _seed(db_session, instructor, colleague, ta)

    with pytest.raises(PermissionError):
        await set_supervisor(db_session, instructor, ta.id, None)


@pytest.mark.asyncio
async def test_an_instructor_may_not_claim_an_unassigned_assistant(db_session):
    # Helping themselves to a spare account is an admin's call, not theirs.
    instructor = _user(UserRoleEnum.instructor)
    ta = _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, instructor, ta)

    with pytest.raises(PermissionError):
        await set_supervisor(db_session, instructor, ta.id, instructor.id)
