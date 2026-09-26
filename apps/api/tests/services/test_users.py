import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from exceptions import (
    Auth0ProvisioningError,
    EmailAlreadyExistsError,
    InvalidStatusTransitionError,
    InvalidSupervisorError,
    UserNotFoundError,
)
from models import Supervision, User, UserRoleEnum, UserRoleEvent, UserStatusEnum, UserStatusEvent
from schemas import UserResponse
from services.users_service import (
    LoginRejection,
    _can_view_user,
    change_user_role,
    create_user,
    deactivate_user,
    delete_user,
    get_user_by_id,
    list_users,
    mark_first_login,
    normalize_email,
    reactivate_user,
    resend_invite,
    resolve_user,
)


# create_user/delete_user call out to Auth0's Management + Authentication
# APIs (DECISION LOG [0.9.0]). These tests exercise the local provisioning/
# deletion logic, not those HTTP calls, so every test gets no-op stubs
# instead. Individual tests override these via monkeypatch when they need to
# assert on the Auth0-facing call itself.
@pytest.fixture(autouse=True)
def _stub_invite_user(monkeypatch):
    async def fake_invite_user(email):
        return f"auth0|{email}"

    async def fake_delete_auth0_user(auth0_user_id):
        return True

    async def fake_find_auth0_user_id_by_email(email):
        return None

    monkeypatch.setattr("services.users_service.invite_user", fake_invite_user)
    monkeypatch.setattr("services.users_service.find_auth0_user_id_by_email", fake_find_auth0_user_id_by_email)
    monkeypatch.setattr("services.users_service.delete_auth0_user", fake_delete_auth0_user)


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


async def _supervise(db, ta, *instructors):
    """Test shortcut for an active supervision link (DECISION LOG [0.21.0])."""
    db.add_all(Supervision(ta_id=ta.id, instructor_id=i.id) for i in instructors)
    await db.commit()
    await db.refresh(ta)


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


@pytest.mark.asyncio
async def test_instructor_sees_only_the_assistants_they_supervise(db_session):
    """Narrowed 2026-08-18 to the delegation chain, which since [0.21.0] is an
    active supervision link - whoever provisioned the TA."""
    instructor = _user(UserRoleEnum.instructor)
    other_instructor = _user(UserRoleEnum.instructor)
    own_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=other_instructor.id)
    other_ta = _user(UserRoleEnum.teaching_assistant, provisioned_by=instructor.id)
    db_session.add_all([instructor, other_instructor, own_ta, other_ta])
    await db_session.commit()
    await _supervise(db_session, own_ta, instructor)
    await _supervise(db_session, other_ta, other_instructor)

    assert _can_view_user(instructor, own_ta) is True
    # Provisioning them grants nothing any more.
    assert _can_view_user(instructor, other_ta) is False
    assert _can_view_user(instructor, other_instructor) is False


@pytest.mark.asyncio
async def test_ta_sees_their_supervisors_and_no_one_else(db_session):
    first, second, stranger = (_user(UserRoleEnum.instructor) for _ in range(3))
    ta = _user(UserRoleEnum.teaching_assistant)
    sibling = _user(UserRoleEnum.teaching_assistant)
    db_session.add_all([first, second, stranger, ta, sibling])
    await db_session.commit()
    await _supervise(db_session, ta, first, second)
    await _supervise(db_session, sibling, first)

    assert _can_view_user(ta, first) is True
    assert _can_view_user(ta, second) is True
    assert _can_view_user(ta, stranger) is False
    assert _can_view_user(ta, sibling) is False


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
async def test_resolve_by_sub_when_already_bound(db_session):
    user = User(id=uuid.uuid4(), email="a@smu.edu.sg", auth0_sub="oid-1", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    resolved = await resolve_user(db_session, sub="oid-1", email="different@smu.edu.sg")
    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_unprovisioned_email_returns_none(db_session):
    resolved = await resolve_user(db_session, sub="oid-x", email="nobody@smu.edu.sg")
    assert isinstance(resolved, LoginRejection)


@pytest.mark.asyncio
async def test_deleted_user_not_resolved(db_session):
    user = _deleted_user(UserRoleEnum.instructor, email="gone@smu.edu.sg")
    user.auth0_sub = "oid-gone"
    db_session.add(user)
    await db_session.commit()

    resolved = await resolve_user(db_session, sub="oid-gone", email="gone@smu.edu.sg")
    assert isinstance(resolved, LoginRejection)


# --- Auth0 credential creation (DECISION LOG [0.7.0]) -----------------------
# Disable Sign Ups means an invitee cannot create their own Auth0 credential,
# so create_user must produce one for them and must not leave a `users` row
# with no way to ever sign in.


@pytest.mark.asyncio
async def test_create_user_invites_via_auth0(db_session):
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    created = await create_user(db_session, admin, "invited@smu.edu.sg", UserRoleEnum.instructor)

    assert created.email == "invited@smu.edu.sg"
    assert created.auth0_sub == "auth0|invited@smu.edu.sg"


@pytest.mark.asyncio
async def test_no_local_row_is_written_when_auth0_credential_creation_fails(db_session, monkeypatch):
    from exceptions import Auth0ProvisioningError

    async def failing_invite_user(email):
        raise Auth0ProvisioningError("Auth0 unreachable")

    monkeypatch.setattr("services.users_service.invite_user", failing_invite_user)

    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    with pytest.raises(Auth0ProvisioningError):
        await create_user(db_session, admin, "orphaned@smu.edu.sg", UserRoleEnum.instructor)

    result = await db_session.execute(select(User).where(User.email == "orphaned@smu.edu.sg"))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_orphaned_auth0_user_is_deleted_when_local_commit_fails(db_session, monkeypatch):
    """The inverse of test_no_local_row_is_written_when_auth0_credential_creation_fails:
    invite_user() succeeds but the local commit right after it doesn't. Without
    a compensating delete, that email is permanently stuck - Auth0 already has
    the credential, so every retry's create call 400s on Auth0's own
    duplicate-email check, even though no `users` row for it ever existed."""

    async def fake_invite_user(email):
        return "auth0|stub-id"

    monkeypatch.setattr("services.users_service.invite_user", fake_invite_user)

    deleted_ids = []

    async def fake_delete_auth0_user(auth0_user_id):
        deleted_ids.append(auth0_user_id)

    monkeypatch.setattr("services.users_service.delete_auth0_user", fake_delete_auth0_user)

    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    async def failing_commit():
        raise RuntimeError("db exploded")

    monkeypatch.setattr(db_session, "commit", failing_commit)

    with pytest.raises(RuntimeError):
        await create_user(db_session, admin, "orphaned2@smu.edu.sg", UserRoleEnum.instructor)

    assert deleted_ids == ["auth0|stub-id"]


@pytest.mark.asyncio
async def test_stale_auth0_credential_is_replaced_not_adopted(db_session, monkeypatch):
    """Auth0 already holds a credential for an email with no live local row (a failed Auth0 delete,
    a recycled address). Adopting it would hand the account to whoever knows that old password, so it
    is deleted and a fresh credential invited instead."""

    async def fake_find(email):
        return "auth0|stale"

    calls = []

    async def fake_delete(auth0_user_id):
        calls.append(("delete", auth0_user_id))
        return True

    async def fake_invite(email):
        calls.append(("invite", email))
        return "auth0|fresh"

    monkeypatch.setattr("services.users_service.find_auth0_user_id_by_email", fake_find)
    monkeypatch.setattr("services.users_service.delete_auth0_user", fake_delete)
    monkeypatch.setattr("services.users_service.invite_user", fake_invite)

    admin = _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin)

    created = await create_user(db_session, admin, "existing@smu.edu.sg", UserRoleEnum.instructor)

    assert created.auth0_sub == "auth0|fresh"
    assert calls == [("delete", "auth0|stale"), ("invite", "existing@smu.edu.sg")]


@pytest.mark.asyncio
async def test_nothing_is_created_when_the_stale_credential_cannot_be_removed(db_session, monkeypatch):
    from exceptions import Auth0ProvisioningError

    async def fake_find(email):
        return "auth0|stale"

    async def failing_delete(auth0_user_id):
        return False

    async def must_not_invite(email):
        raise AssertionError("invited while the stale credential still exists")

    monkeypatch.setattr("services.users_service.find_auth0_user_id_by_email", fake_find)
    monkeypatch.setattr("services.users_service.delete_auth0_user", failing_delete)
    monkeypatch.setattr("services.users_service.invite_user", must_not_invite)

    admin = _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin)

    with pytest.raises(Auth0ProvisioningError):
        await create_user(db_session, admin, "existing2@smu.edu.sg", UserRoleEnum.instructor)

    result = await db_session.execute(select(User).where(User.email == "existing2@smu.edu.sg"))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_create_user_reuses_a_previously_deleted_row(db_session):
    # Repeated delete + re-provision of the same email must not pile up
    # duplicate rows that differ only in which one holds the live auth0_sub.
    admin = _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin)

    first = await create_user(db_session, admin, "recycled@smu.edu.sg", UserRoleEnum.instructor)
    first_id = first.id
    await delete_user(db_session, admin, first_id)

    second = await create_user(db_session, admin, "recycled@smu.edu.sg", UserRoleEnum.teaching_assistant)

    assert second.id == first_id
    assert second.status == UserStatusEnum.active
    assert second.role == UserRoleEnum.teaching_assistant

    rows = (await db_session.execute(select(User).where(User.email == "recycled@smu.edu.sg"))).scalars().all()
    assert len(rows) == 1

    events = (
        (await db_session.execute(select(UserStatusEvent).where(UserStatusEvent.user_id == first_id))).scalars().all()
    )
    assert any(e.from_status == UserStatusEnum.deleted and e.to_status == UserStatusEnum.active for e in events)
    # A re-used address may be a different person: the old name does not carry over.
    assert second.display_name is None


@pytest.mark.asyncio
async def test_create_user_still_rejects_a_live_duplicate_email(db_session):
    admin = _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin)

    await create_user(db_session, admin, "taken@smu.edu.sg", UserRoleEnum.instructor)

    with pytest.raises(EmailAlreadyExistsError):
        await create_user(db_session, admin, "taken@smu.edu.sg", UserRoleEnum.instructor)


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
async def test_ta_cannot_create_any_user(db_session):
    ta = _user(UserRoleEnum.teaching_assistant)
    db_session.add(ta)
    await db_session.commit()

    with pytest.raises(PermissionError):
        await create_user(db_session, ta, "nope@smu.edu.sg", UserRoleEnum.teaching_assistant)


@pytest.mark.asyncio
async def test_an_instructor_cannot_create_any_user(db_session):
    # Instructors add TAs through POST /api/users/teaching-assistants
    # (DECISION LOG [0.21.0]); POST /api/users is the admin's.
    instructor = _user(UserRoleEnum.instructor)
    db_session.add(instructor)
    await db_session.commit()

    for role in (UserRoleEnum.instructor, UserRoleEnum.teaching_assistant):
        with pytest.raises(PermissionError):
            await create_user(db_session, instructor, f"{role.value}@smu.edu.sg", role)


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


@pytest.mark.asyncio
async def test_a_new_account_has_no_name_and_no_supervisor(db_session):
    # The person picks their own name after first sign-in; an admin-created TA
    # waits for POST /api/users/{id}/supervisors. DECISION LOG [0.21.0].
    admin = _user(UserRoleEnum.root_admin)
    db_session.add(admin)
    await db_session.commit()

    created = await create_user(db_session, admin, "fresh-ta@smu.edu.sg", UserRoleEnum.teaching_assistant)

    assert created.display_name is None
    assert created.supervisor_ids == []
    assert created.provisioned_by == admin.id


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
    own_ta = _user(UserRoleEnum.teaching_assistant)
    other_ta = _user(UserRoleEnum.teaching_assistant)
    db_session.add_all([own_ta, other_ta])
    await db_session.commit()
    await _supervise(db_session, own_ta, instructor)
    await _supervise(db_session, other_ta, other_instructor)

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
    own_ta = _user(UserRoleEnum.teaching_assistant)
    db_session.add(own_ta)
    await db_session.commit()
    await _supervise(db_session, own_ta, instructor)

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
async def test_login_matches_an_already_bound_row_regardless_of_claim_case(db_session):
    user = User(id=uuid.uuid4(), email="ada@smu.edu.sg", auth0_sub="oid-ada", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    resolved = await resolve_user(db_session, sub="oid-ada", email="ADA@SMU.EDU.SG")

    assert resolved is not None
    assert resolved.id == user.id


@pytest.mark.asyncio
async def test_case_folding_does_not_let_an_email_claim_take_a_bound_row(db_session):
    # The S0 guard must survive normalisation: folding case must not turn a
    # rejected rebind into an accepted one.
    victim = User(id=uuid.uuid4(), email="victim@smu.edu.sg", auth0_sub="victim-oid", role=UserRoleEnum.root_admin)
    db_session.add(victim)
    await db_session.commit()

    resolved = await resolve_user(db_session, sub="attacker-oid", email="VICTIM@smu.edu.sg")

    assert isinstance(resolved, LoginRejection)
    await db_session.refresh(victim)
    assert victim.auth0_sub == "victim-oid"


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


@pytest.mark.asyncio
async def test_delete_user_removes_the_auth0_credential(db_session, monkeypatch):
    deleted_ids = []

    async def fake_delete_auth0_user(auth0_user_id):
        deleted_ids.append(auth0_user_id)
        return True

    monkeypatch.setattr("services.users_service.delete_auth0_user", fake_delete_auth0_user)

    admin = _user(UserRoleEnum.root_admin)
    ta = _user(UserRoleEnum.teaching_assistant)
    ta.auth0_sub = "auth0|ta-sub"
    await _seed(db_session, admin, ta)

    result = await delete_user(db_session, admin, ta.id)

    assert deleted_ids == ["auth0|ta-sub"]
    assert result.auth0_sub is None


@pytest.mark.asyncio
async def test_delete_user_keeps_the_sub_when_auth0_delete_fails(db_session, monkeypatch):
    # A failed Auth0 delete (e.g. the M2M app missing delete:users) must not
    # be recorded as a success - clearing auth0_sub anyway would hide a still
    # -live Auth0 credential behind a row that looks fully cleaned up, and a
    # later re-provision of this email would 400 on Auth0's own duplicate
    # check with nothing left here to explain why.
    async def fake_delete_auth0_user(auth0_user_id):
        return False

    monkeypatch.setattr("services.users_service.delete_auth0_user", fake_delete_auth0_user)

    admin = _user(UserRoleEnum.root_admin)
    ta = _user(UserRoleEnum.teaching_assistant)
    ta.auth0_sub = "auth0|ta-sub"
    await _seed(db_session, admin, ta)

    result = await delete_user(db_session, admin, ta.id)

    assert result.status == UserStatusEnum.deleted
    assert result.auth0_sub == "auth0|ta-sub"


@pytest.mark.asyncio
async def test_delete_user_skips_auth0_call_when_never_logged_in(db_session, monkeypatch):
    # Guards against a regression back to no-op-on-None silently swallowing a
    # real id instead of only skipping a genuinely absent one.
    async def fail_if_called(auth0_user_id):
        raise AssertionError("should not call Auth0 for a user with no auth0_sub")

    monkeypatch.setattr("services.users_service.delete_auth0_user", fail_if_called)

    admin = _user(UserRoleEnum.root_admin)
    ta = _user(UserRoleEnum.teaching_assistant)
    ta.auth0_sub = None
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


# --- role changes -----------------------------------------------------------


@pytest.mark.asyncio
async def test_change_user_role_records_an_event(db_session):
    admin = _user(UserRoleEnum.root_admin)
    ta = _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, ta)

    result = await change_user_role(db_session, admin, ta.id, UserRoleEnum.instructor)

    assert result.role == UserRoleEnum.instructor
    events = (await db_session.execute(select(UserRoleEvent).where(UserRoleEvent.user_id == ta.id))).scalars().all()
    assert len(events) == 1
    assert events[0].actor_id == admin.id
    assert events[0].from_role == UserRoleEnum.teaching_assistant
    assert events[0].to_role == UserRoleEnum.instructor


@pytest.mark.asyncio
async def test_change_user_role_cannot_target_root_admin(db_session):
    admin = _user(UserRoleEnum.root_admin)
    other_admin = _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin, other_admin)

    with pytest.raises(PermissionError):
        await change_user_role(db_session, admin, other_admin.id, UserRoleEnum.instructor)


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
async def test_a_pending_ta_can_be_deactivated_by_root_admin(db_session):
    # Pending = never signed in. Display-only, not a permission fence (DECISION LOG [0.20.0]).
    admin = _user(UserRoleEnum.root_admin)
    other = _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, other)

    assert (await deactivate_user(db_session, admin, other.id)).status == UserStatusEnum.deactivated


@pytest.mark.asyncio
async def test_deletion_is_root_admin_only(db_session):
    # Deletion is terminal and root_admin only. An instructor offboards a TA by
    # ending their own supervision link (DECISION LOG [0.21.0]).
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
    # someone bars them from ever holding an account again. The deleted row is
    # reused rather than replaced (see test_create_user_reuses_a_previously_
    # deleted_row for that mechanism in detail).
    admin = _user(UserRoleEnum.root_admin)
    ta = _user(UserRoleEnum.teaching_assistant, email="returning@smu.edu.sg")
    await _seed(db_session, admin, ta)
    await delete_user(db_session, admin, ta.id)

    fresh = await create_user(db_session, admin, "returning@smu.edu.sg", UserRoleEnum.instructor)

    assert fresh.id == ta.id
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

    assert await resolve_user(db_session, sub="o1", email="off@smu.edu.sg") is LoginRejection.deactivated
    assert await resolve_user(db_session, sub="o2", email="gone@smu.edu.sg") is LoginRejection.deleted
    assert await resolve_user(db_session, sub="o3", email="nobody@smu.edu.sg") is LoginRejection.not_provisioned


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
    own = _deactivated_user(UserRoleEnum.teaching_assistant)
    other = _deactivated_user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, instructor, other_instructor, own, other)
    await _supervise(db_session, own, instructor)
    await _supervise(db_session, other, other_instructor)

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
# An admin may name a TA's first supervisor at creation; the link lands in the
# same commit as the account (DECISION LOG [0.21.0]). provisioned_by records
# only who sent the invite.


@pytest.mark.asyncio
async def test_admin_can_name_the_supervising_instructor(db_session):
    admin, instructor = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.instructor)
    await _seed(db_session, admin, instructor)

    created = await create_user(
        db_session, admin, "placed@smu.edu.sg", UserRoleEnum.teaching_assistant, supervisor_id=instructor.id
    )

    assert created.supervisor_ids == [instructor.id]
    assert created.provisioned_by == admin.id


@pytest.mark.asyncio
async def test_an_admin_created_assistant_with_no_instructor_is_unassigned(db_session):
    # An admin does not supervise; the TA waits for a link.
    admin = _user(UserRoleEnum.root_admin)
    await _seed(db_session, admin)

    created = await create_user(db_session, admin, "floating@smu.edu.sg", UserRoleEnum.teaching_assistant)

    assert created.supervisor_ids == []
    assert created.provisioned_by == admin.id


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


@pytest.mark.asyncio
async def test_a_new_user_has_never_signed_in(db_session):
    user = _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, user)

    await db_session.refresh(user)

    assert user.first_login_at is None
    assert UserResponse.model_validate(user).first_login_at is None


@pytest.mark.asyncio
async def test_first_login_is_stamped_once_and_never_moved(db_session):
    user = _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, user)

    await mark_first_login(db_session, user)
    first = user.first_login_at
    assert first is not None

    await mark_first_login(db_session, user)
    assert user.first_login_at == first


@pytest.mark.asyncio
async def test_reprovisioning_a_deleted_email_makes_it_pending_again(db_session):
    admin = _user(UserRoleEnum.root_admin)
    old = _deleted_user(UserRoleEnum.teaching_assistant, email="back@smu.edu.sg")
    old.first_login_at = datetime.now(UTC)
    await _seed(db_session, admin, old)

    again = await create_user(db_session, admin, "back@smu.edu.sg", UserRoleEnum.teaching_assistant)

    assert again.id == old.id
    assert again.first_login_at is None


@pytest.fixture
def sent_invites(monkeypatch):
    sent: list[str] = []

    async def fake_resend(email):
        sent.append(email)

    monkeypatch.setattr("services.users_service.resend_invite_email", fake_resend)
    return sent


@pytest.mark.asyncio
async def test_an_instructor_can_resend_to_their_own_pending_assistant(db_session, sent_invites):
    instructor = _user(UserRoleEnum.instructor)
    own = _user(UserRoleEnum.teaching_assistant, email="own@smu.edu.sg")
    await _seed(db_session, instructor, own)
    await _supervise(db_session, own, instructor)

    result = await resend_invite(db_session, instructor, own.id)

    assert result.id == own.id
    assert sent_invites == ["own@smu.edu.sg"]


@pytest.mark.asyncio
async def test_resend_is_refused_for_someone_elses_assistant(db_session, sent_invites):
    instructor = _user(UserRoleEnum.instructor)
    other = _user(UserRoleEnum.instructor)
    theirs = _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, instructor, other, theirs)
    await _supervise(db_session, theirs, other)

    with pytest.raises(PermissionError):
        await resend_invite(db_session, instructor, theirs.id)
    assert sent_invites == []


@pytest.mark.asyncio
async def test_resend_is_refused_once_the_person_has_signed_in(db_session, sent_invites):
    admin = _user(UserRoleEnum.root_admin)
    active = _user(UserRoleEnum.teaching_assistant)
    active.first_login_at = datetime.now(UTC)
    await _seed(db_session, admin, active)

    with pytest.raises(InvalidStatusTransitionError):
        await resend_invite(db_session, admin, active.id)
    assert sent_invites == []


@pytest.mark.asyncio
async def test_resend_is_refused_for_a_deactivated_invitee(db_session, sent_invites):
    admin = _user(UserRoleEnum.root_admin)
    paused = _user(UserRoleEnum.teaching_assistant)
    paused.status = UserStatusEnum.deactivated
    await _seed(db_session, admin, paused)

    with pytest.raises(InvalidStatusTransitionError):
        await resend_invite(db_session, admin, paused.id)


@pytest.mark.asyncio
async def test_a_refused_send_surfaces_as_an_auth0_error_and_changes_nothing(db_session, monkeypatch):
    async def boom(email):
        raise Auth0ProvisioningError("nope")

    monkeypatch.setattr("services.users_service.resend_invite_email", boom)
    admin = _user(UserRoleEnum.root_admin)
    pending = _user(UserRoleEnum.teaching_assistant)
    await _seed(db_session, admin, pending)

    with pytest.raises(Auth0ProvisioningError):
        await resend_invite(db_session, admin, pending.id)


@pytest.mark.asyncio
async def test_a_bad_supervisor_is_refused_before_anyone_is_invited(db_session, monkeypatch):
    # Validation runs before the Auth0 call, so a refused request leaves no
    # credential to clean up.
    invited = []

    async def record(email):
        invited.append(email)
        return f"auth0|{email}"

    monkeypatch.setattr("services.users_service.invite_user", record)
    admin, off = _user(UserRoleEnum.root_admin), _deactivated_user(UserRoleEnum.instructor)
    await _seed(db_session, admin, off)

    with pytest.raises(InvalidSupervisorError):
        await create_user(db_session, admin, "early@smu.edu.sg", UserRoleEnum.teaching_assistant, off.id)

    assert invited == []
    assert (await db_session.execute(select(User).where(User.email == "early@smu.edu.sg"))).first() is None


@pytest.mark.asyncio
async def test_a_failed_commit_leaves_no_account_no_link_and_no_credential(db_session, monkeypatch):
    # All or nothing (DECISION LOG [0.21.0]): the account, the first link and
    # the Auth0 credential land together or not at all.
    removed = []

    async def record_delete(auth0_user_id):
        removed.append(auth0_user_id)
        return True

    monkeypatch.setattr("services.users_service.delete_auth0_user", record_delete)
    admin, instructor = _user(UserRoleEnum.root_admin), _user(UserRoleEnum.instructor)
    await _seed(db_session, admin, instructor)

    async def fail_commit():
        raise RuntimeError("database went away")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError):
        await create_user(db_session, admin, "atomic@smu.edu.sg", UserRoleEnum.teaching_assistant, instructor.id)
    monkeypatch.delattr(db_session, "commit")  # back to the real method

    assert removed == ["auth0|atomic@smu.edu.sg"]
    assert (await db_session.execute(select(User).where(User.email == "atomic@smu.edu.sg"))).first() is None
    assert (await db_session.execute(select(Supervision))).first() is None


@pytest.mark.asyncio
async def test_an_instructor_lists_every_assistant_they_share(db_session):
    # Many-to-many: a TA shared by two instructors is on both lists.
    first, second = _user(UserRoleEnum.instructor), _user(UserRoleEnum.instructor)
    shared = _user(UserRoleEnum.teaching_assistant)
    db_session.add_all([first, second, shared])
    await db_session.commit()
    await _supervise(db_session, shared, first, second)

    for instructor in (first, second):
        rows, _ = await list_users(db_session, instructor)
        assert [row.id for row in rows] == [shared.id]
