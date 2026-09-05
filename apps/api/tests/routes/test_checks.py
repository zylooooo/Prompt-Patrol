import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from db import get_db
from main import app
from models import Check, User, UserRoleEnum
from routes.checks_routes import require_any_user, require_screening
from services.detector_client import MODEL_VERSION, Score


@pytest.fixture
def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


async def _signed_in(client, db_session, role=UserRoleEnum.teaching_assistant, email=None):
    """Persists the user before authenticating as them. `checks.actor_id` is a
    real foreign key, so an in-memory User that was never inserted only works
    because SQLite leaves FK enforcement off - on Postgres the insert fails.

    An assistant gets a supervisor. `provisioned_by` is what grants screening
    access, so a fixture without one describes somebody the server refuses -
    which is a case worth testing deliberately, not by accident in every test.
    """
    provisioned_by = None
    if role == UserRoleEnum.teaching_assistant:
        supervisor = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@smu.edu.sg", role=UserRoleEnum.instructor)
        db_session.add(supervisor)
        await db_session.commit()
        provisioned_by = supervisor.id

    user = User(
        id=uuid.uuid4(),
        email=email or f"{uuid.uuid4()}@smu.edu.sg",
        role=role,
        provisioned_by=provisioned_by,
    )
    db_session.add(user)
    await db_session.commit()

    async def override():
        return user

    client.app.dependency_overrides[require_any_user] = override
    client.app.dependency_overrides[require_screening] = override
    return user


AI_LIKE = "Furthermore, this ensures the system consequently facilitates a robust outcome."
HUMAN_LIKE = "idk it just kinda works because we set the pointer to null before freeing it"


@pytest.mark.asyncio
async def test_create_check_without_session_returns_401(client):
    response = client.post("/api/checks", json={"answer_text": HUMAN_LIKE})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_check_happy_path(client, db_session):
    user = await _signed_in(client, db_session, email="ta@smu.edu.sg")

    with patch(
        "services.checks_service.score_text",
        new=AsyncMock(return_value=Score(raw_score=0.9, truncated=False)),
    ):
        response = client.post(
            "/api/checks",
            json={"answer_text": AI_LIKE, "strictness": "standard"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] == "ai_generated"
    assert body["raw_score"] == 0.9
    assert body["actor_id"] == str(user.id)
    assert body["detector"]["model_version"]
    assert body["detector"]["used_question_text"] is False
    assert response.headers["location"] == f"/api/checks/{body['check_id']}"


@pytest.mark.asyncio
async def test_create_check_abstains_on_short_answer(client, db_session):
    await _signed_in(client, db_session, email="ta2@smu.edu.sg")

    with patch(
        "services.checks_service.score_text",
        new=AsyncMock(return_value=Score(raw_score=0.9, truncated=False)),
    ):
        response = client.post(
            "/api/checks",
            json={"answer_text": "too short reply"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] == "uncertain"
    assert body["abstain_reason"] == "answer_too_short"


@pytest.mark.asyncio
async def test_create_check_rejects_unknown_field(client, db_session):
    await _signed_in(client, db_session, email="ta3@smu.edu.sg")

    response = client.post(
        "/api/checks",
        json={"answer_text": HUMAN_LIKE, "instructor_id": str(uuid.uuid4())},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_check_rejects_too_short_below_floor(client, db_session):
    await _signed_in(client, db_session, email="ta4@smu.edu.sg")

    response = client.post("/api/checks", json={"answer_text": "short"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_get_detector_capabilities(client, db_session):
    await _signed_in(client, db_session, email="ta5@smu.edu.sg")

    response = client.get("/api/detector")
    assert response.status_code == 200
    body = response.json()
    assert body["requires_question_text"] is False
    assert {level["level"] for level in body["strictness_levels"]} == {
        "lenient",
        "standard",
        "strict",
    }


@pytest.mark.asyncio
async def test_detector_status_without_session_returns_401(client):
    response = client.get("/api/detector/status")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_detector_status_reports_ready(client, db_session):
    await _signed_in(client, db_session, email="ta6@smu.edu.sg")

    with patch("routes.checks_routes.detector_health", new=AsyncMock(return_value="ready")):
        response = client.get("/api/detector/status")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "model_version": MODEL_VERSION}


@pytest.mark.asyncio
@pytest.mark.parametrize("reported", ["loading", "unavailable"])
async def test_a_detector_that_cannot_score_is_still_a_200(client, db_session, reported):
    """The caller is a status badge. Answering 5xx would blank it at the one
    moment it has something worth saying, so the trouble goes in the body."""
    await _signed_in(client, db_session, email=f"ta-{reported}@smu.edu.sg")

    with patch("routes.checks_routes.detector_health", new=AsyncMock(return_value=reported)):
        response = client.get("/api/detector/status")

    assert response.status_code == 200
    assert response.json()["status"] == reported


SCORED = AsyncMock(return_value=Score(raw_score=0.9, truncated=False))


async def _make_check(client, **body):
    with patch("services.checks_service.score_text", new=SCORED):
        return client.post("/api/checks", json={"answer_text": AI_LIKE, **body})


@pytest.mark.asyncio
async def test_a_check_survives_the_request_that_made_it(client, db_session):
    """The point of the whole phase: history used to live in one browser's
    localStorage, so clearing it erased the record."""
    await _signed_in(client, db_session)
    created = (await _make_check(client)).json()

    fetched = client.get(f"/api/checks/{created['check_id']}")

    assert fetched.status_code == 200
    assert fetched.json()["check_id"] == created["check_id"]
    assert fetched.json()["raw_score"] == 0.9


@pytest.mark.asyncio
async def test_the_location_header_now_points_somewhere(client, db_session):
    await _signed_in(client, db_session)
    response = await _make_check(client)

    assert client.get(response.headers["location"]).status_code == 200


@pytest.mark.asyncio
async def test_listing_returns_only_your_own_checks(client, db_session):
    mine = await _signed_in(client, db_session, email="mine@smu.edu.sg")
    await _make_check(client, external_ref="MINE")

    # A second author, whose check must not appear in the first one's list.
    await _signed_in(client, db_session, email="theirs@smu.edu.sg")
    await _make_check(client, external_ref="THEIRS")

    async def back_to_mine():
        return mine

    client.app.dependency_overrides[require_any_user] = back_to_mine
    items = client.get("/api/checks").json()["items"]

    assert [i["external_ref"] for i in items] == ["MINE"]


@pytest.mark.asyncio
async def test_listing_filters_by_verdict(client, db_session):
    await _signed_in(client, db_session)
    await _make_check(client, external_ref="AI")
    with patch("services.checks_service.score_text", new=AsyncMock(return_value=Score(raw_score=0.1, truncated=False))):
        client.post("/api/checks", json={"answer_text": HUMAN_LIKE, "external_ref": "HUMAN"})

    items = client.get("/api/checks?verdict=ai_generated").json()["items"]

    assert [i["external_ref"] for i in items] == ["AI"]


@pytest.mark.asyncio
async def test_listing_filters_by_batch_id(client, db_session):
    await _signed_in(client, db_session)
    batch_id = str(uuid.uuid4())
    await _make_check(client, external_ref="IN_BATCH", batch_id=batch_id)
    await _make_check(client, external_ref="NOT_IN_BATCH")

    items = client.get(f"/api/checks?batch_id={batch_id}").json()["items"]

    assert [i["external_ref"] for i in items] == ["IN_BATCH"]


@pytest.mark.asyncio
async def test_listing_filters_by_date_range_inclusive(client, db_session):
    await _signed_in(client, db_session)
    created = (await _make_check(client, external_ref="R")).json()
    created_at = created["created_at"]

    on_boundary = client.get(f"/api/checks?from={created_at}&to={created_at}").json()["items"]
    before = client.get("/api/checks?to=2000-01-01T00:00:00Z").json()["items"]

    assert [i["external_ref"] for i in on_boundary] == ["R"]
    assert before == []


@pytest.mark.asyncio
async def test_listing_inverted_date_range_is_just_empty_not_an_error(client, db_session):
    await _signed_in(client, db_session)
    await _make_check(client)

    response = client.get("/api/checks?from=2099-01-01T00:00:00Z&to=2000-01-01T00:00:00Z")

    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.asyncio
async def test_actor_id_filter_is_silently_ignored_for_a_non_admin(client, db_session):
    """Override rather than reject - rejecting would confirm the other id
    exists."""
    mine = await _signed_in(client, db_session, email="mine2@smu.edu.sg")
    await _make_check(client, external_ref="MINE")

    await _signed_in(client, db_session, email="theirs2@smu.edu.sg")
    theirs = await _make_check(client, external_ref="THEIRS")
    theirs_actor_id = theirs.json()["actor_id"]

    async def back_to_mine():
        return mine

    client.app.dependency_overrides[require_any_user] = back_to_mine
    items = client.get(f"/api/checks?actor_id={theirs_actor_id}").json()["items"]

    assert [i["external_ref"] for i in items] == ["MINE"]


@pytest.mark.asyncio
async def test_actor_id_filter_is_honoured_for_a_root_admin(client, db_session):
    await _signed_in(client, db_session, email="someone2@smu.edu.sg")
    someone = await _make_check(client, external_ref="SOMEONE")
    someone_actor_id = someone.json()["actor_id"]

    await _signed_in(client, db_session, email="other@smu.edu.sg")
    await _make_check(client, external_ref="OTHER")

    await _signed_in(client, db_session, role=UserRoleEnum.root_admin, email="admin2@smu.edu.sg")
    items = client.get(f"/api/checks?actor_id={someone_actor_id}").json()["items"]

    assert [i["external_ref"] for i in items] == ["SOMEONE"]


@pytest.mark.asyncio
async def test_listing_includes_summary_fields_the_history_table_needs(client, db_session):
    """raw_score, strictness_applied, and batch_file_name are flattened onto
    CheckSummary (not just CheckResult) so the history table's Score column,
    per-batch strictness tag, and batch file name survive a reload - see
    openapi.yaml DECISION LOG [0.5.8]."""
    await _signed_in(client, db_session)
    batch_id = str(uuid.uuid4())
    await _make_check(
        client, strictness="strict", batch_id=batch_id, batch_file_name="midterm.csv"
    )

    item = client.get("/api/checks").json()["items"][0]

    assert item["raw_score"] == 0.9
    assert item["strictness_applied"] == "strict"
    assert item["answer_text"] == AI_LIKE
    assert item["batch_file_name"] == "midterm.csv"


@pytest.mark.asyncio
async def test_answer_char_len_is_captured_regardless_of_retention(client, db_session):
    """Not on the wire (DB-only, for E3's reliability-vs-answer-length
    analysis) - captured before any conditional nulling so it survives a
    future purge of answer_text."""
    await _signed_in(client, db_session)
    kept = (await _make_check(client, external_ref="KEPT")).json()
    dropped = (await _make_check(client, external_ref="DROPPED", retain_answer=False)).json()

    kept_row = (
        await db_session.execute(select(Check).where(Check.id == uuid.UUID(kept["check_id"])))
    ).scalar_one()
    dropped_row = (
        await db_session.execute(select(Check).where(Check.id == uuid.UUID(dropped["check_id"])))
    ).scalar_one()

    assert kept_row.answer_char_len == len(AI_LIKE)
    assert kept_row.retain_answer is True
    assert dropped_row.answer_char_len == len(AI_LIKE)
    assert dropped_row.retain_answer is False
    assert dropped_row.answer_text is None


@pytest.mark.asyncio
async def test_another_users_check_is_404_not_403(client, db_session):
    """404 for both "no such check" and "not yours", so the endpoint cannot be
    used to discover that someone else's check exists."""
    await _signed_in(client, db_session, email="author@smu.edu.sg")
    theirs = (await _make_check(client)).json()["check_id"]

    await _signed_in(client, db_session, email="stranger@smu.edu.sg")

    assert client.get(f"/api/checks/{theirs}").status_code == 404
    assert client.get(f"/api/checks/{uuid.uuid4()}").status_code == 404


@pytest.mark.asyncio
async def test_a_root_admin_reads_everyones_checks(client, db_session):
    await _signed_in(client, db_session, email="someone@smu.edu.sg")
    theirs = (await _make_check(client)).json()["check_id"]

    await _signed_in(client, db_session, role=UserRoleEnum.root_admin, email="admin@smu.edu.sg")

    assert client.get(f"/api/checks/{theirs}").status_code == 200
    assert len(client.get("/api/checks").json()["items"]) == 1


@pytest.mark.asyncio
async def test_retain_answer_false_stores_the_judgement_without_the_text(client, db_session):
    await _signed_in(client, db_session)
    created = (await _make_check(client, retain_answer=False)).json()

    fetched = client.get(f"/api/checks/{created['check_id']}").json()

    assert fetched["answer_text"] is None
    assert fetched["verdict"] == "ai_generated"
    assert fetched["raw_score"] == 0.9


@pytest.mark.asyncio
async def test_the_detector_settings_are_stored_not_re_derived(client, db_session):
    """A recalibrated detector must not rewrite what a past verdict was based on."""
    await _signed_in(client, db_session)
    created = (await _make_check(client, strictness="strict")).json()

    fetched = client.get(f"/api/checks/{created['check_id']}").json()["detector"]

    assert fetched["strictness_applied"] == "strict"
    assert fetched["threshold_applied"] == 0.65
    assert fetched["target_fpr"] == 0.001


@pytest.mark.asyncio
async def test_listing_is_newest_first_and_pages(client, db_session):
    await _signed_in(client, db_session)
    for i in range(5):
        await _make_check(client, external_ref=f"R{i}")

    first = client.get("/api/checks?limit=2").json()
    assert len(first["items"]) == 2
    assert first["next_cursor"]

    second = client.get(f"/api/checks?limit=2&cursor={first['next_cursor']}").json()
    assert len(second["items"]) == 2

    seen = [i["external_ref"] for i in first["items"] + second["items"]]
    assert len(set(seen)) == 4, "a page boundary repeated or skipped a row"


@pytest.mark.asyncio
async def test_listing_caps_the_page_size(client, db_session):
    await _signed_in(client, db_session)

    assert client.get("/api/checks?limit=100").status_code == 200
    assert client.get("/api/checks?limit=101").status_code == 422


@pytest.mark.asyncio
async def test_a_bad_cursor_is_400_not_500(client, db_session):
    await _signed_in(client, db_session)

    assert client.get("/api/checks?cursor=not-base64").status_code == 400


# --- screening needs a supervisor -------------------------------------------
# The SPA refuses an unsupervised assistant, but it decides that from the session
# payload it is holding and can be skipped entirely. These drive the real
# dependency with a real session cookie - no override - so the check being tested
# is the one that actually runs.


async def _really_signed_in(client, db_session, role=UserRoleEnum.teaching_assistant, provisioned_by=None):
    from services import create_session

    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@smu.edu.sg",
        role=role,
        provisioned_by=provisioned_by,
    )
    db_session.add(user)
    await db_session.commit()
    client.cookies.set("__Host-session", await create_session(db_session, user.id))
    return user


@pytest.mark.asyncio
async def test_an_unsupervised_assistant_cannot_screen(client, db_session):
    await _really_signed_in(client, db_session)

    response = client.post("/api/checks", json={"answer_text": HUMAN_LIKE})

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_the_refusal_is_the_reason_not_a_bare_forbidden(client, db_session):
    # They can act on this one: it names what is missing and who fixes it.
    await _really_signed_in(client, db_session)

    response = client.post("/api/checks", json={"answer_text": HUMAN_LIKE})

    assert "not assigned to an instructor" in response.json()["detail"]


@pytest.mark.asyncio
async def test_a_supervised_assistant_can_screen(client, db_session):
    instructor = await _really_signed_in(client, db_session, role=UserRoleEnum.instructor)
    client.cookies.clear()
    await _really_signed_in(client, db_session, provisioned_by=instructor.id)

    with patch(
        "services.checks_service.score_text",
        new=AsyncMock(return_value=Score(raw_score=0.9, truncated=False)),
    ):
        response = client.post("/api/checks", json={"answer_text": AI_LIKE})

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_an_instructor_screens_without_a_supervisor_of_their_own(client, db_session):
    # The gate reads "an assistant needs a supervisor", not "everybody needs
    # one" - the second shape would lock out every instructor and admin.
    await _really_signed_in(client, db_session, role=UserRoleEnum.instructor)

    with patch(
        "services.checks_service.score_text",
        new=AsyncMock(return_value=Score(raw_score=0.9, truncated=False)),
    ):
        response = client.post("/api/checks", json={"answer_text": AI_LIKE})

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_a_root_admin_screens_without_a_supervisor(client, db_session):
    await _really_signed_in(client, db_session, role=UserRoleEnum.root_admin)

    with patch(
        "services.checks_service.score_text",
        new=AsyncMock(return_value=Score(raw_score=0.9, truncated=False)),
    ):
        response = client.post("/api/checks", json={"answer_text": AI_LIKE})

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_an_unsupervised_assistant_may_still_read_their_own_history(client, db_session):
    # Deliberate: reading back your own past work is not screening. Being
    # unassigned by an admin revokes the session anyway, so the reachable case
    # here is a script-provisioned account that has no history to read.
    await _really_signed_in(client, db_session)

    response = client.get("/api/checks")

    assert response.status_code == 200
    assert response.json()["items"] == []
