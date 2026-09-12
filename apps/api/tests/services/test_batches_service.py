import uuid
from unittest.mock import patch

import pytest

from models import Batch, User, UserRoleEnum
from services.batches_service import cancel_batch, create_batch, get_batch_progress, parse_and_validate

GOOD_CSV = (
    "external_ref,answer_text\n"
    "stu-1,This is a perfectly reasonable answer with enough words.\n"
    "stu-2,Another answer that is also long enough to pass validation.\n"
)

MAPPED_CSV = (
    "Student ID,Response\n"
    "stu-1,This is a perfectly reasonable answer with enough words.\n"
)

BAD_ROW_CSV = (
    "external_ref,answer_text\n"
    "stu-1,too short\n"
    "stu-2,This one is long enough to pass every validation rule we have.\n"
)


def test_parse_and_validate_happy_path():
    rows, failures = parse_and_validate(GOOD_CSV, column_mapping=None, requires_question_text=False)
    assert len(rows) == 2
    assert failures == []
    assert rows[0]["external_ref"] == "stu-1"


def test_parse_and_validate_applies_column_mapping():
    mapping = {"Student ID": "external_ref", "Response": "answer_text"}
    rows, failures = parse_and_validate(MAPPED_CSV, column_mapping=mapping, requires_question_text=False)
    assert len(rows) == 1
    assert failures == []
    assert rows[0]["external_ref"] == "stu-1"


def test_parse_and_validate_skips_bad_rows_and_flags_them():
    rows, failures = parse_and_validate(BAD_ROW_CSV, column_mapping=None, requires_question_text=False)
    assert len(rows) == 1
    assert rows[0]["external_ref"] == "stu-2"
    assert len(failures) == 1
    assert failures[0]["row_number"] == 2
    assert failures[0]["external_ref"] == "stu-1"
    assert "answer_text" in failures[0]["reason"]


def test_parse_and_validate_requires_question_text_when_flagged():
    rows, failures = parse_and_validate(GOOD_CSV, column_mapping=None, requires_question_text=True)
    assert rows == []
    assert len(failures) == 2
    assert all("question_text" in f["reason"] for f in failures)


@pytest.mark.asyncio
async def test_create_batch_writes_batch_row_and_failures_and_enqueues(db_session):
    user = User(id=uuid.uuid4(), email="instr2@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    with (
        patch("services.batches_service.download_object", return_value=BAD_ROW_CSV),
        patch("services.batches_service.enqueue_row") as mock_enqueue,
    ):
        batch = await create_batch(
            db_session,
            actor_id=user.id,
            upload_key="batches/fake-key.csv",
            file_name="answers.csv",
            strictness="standard",
            retain_answer=True,
            column_mapping=None,
            requires_question_text=False,
        )

    assert isinstance(batch, Batch)
    # 1 valid row (stu-2) + 1 pre-flight-rejected row (stu-1) - row_total
    # covers the whole file so completed+failed+pending==row_total holds.
    assert batch.row_total == 2
    assert mock_enqueue.call_count == 1
    enqueued_payload = mock_enqueue.call_args.args[0]
    assert enqueued_payload["batch_id"] == str(batch.id)
    assert enqueued_payload["actor_id"] == str(user.id)

    progress = await get_batch_progress(db_session, user, batch.id)
    assert progress["row_total"] == 2
    assert progress["pending"] == 1
    assert progress["completed"] == 0
    assert progress["failed"] == 1
    assert len(progress["failures"]) == 1
    assert progress["failures"][0].external_ref == "stu-1"
    assert "answer_text" in progress["failures"][0].reason


@pytest.mark.asyncio
async def test_get_batch_progress_none_for_other_actor(db_session):
    owner = User(id=uuid.uuid4(), email="owner@smu.edu.sg", role=UserRoleEnum.instructor)
    other = User(id=uuid.uuid4(), email="other@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add_all([owner, other])
    await db_session.commit()

    with (
        patch("services.batches_service.download_object", return_value=GOOD_CSV),
        patch("services.batches_service.enqueue_row"),
    ):
        batch = await create_batch(
            db_session,
            actor_id=owner.id,
            upload_key="batches/fake-key.csv",
            file_name="answers.csv",
            strictness="standard",
            retain_answer=True,
            column_mapping=None,
            requires_question_text=False,
        )

    assert await get_batch_progress(db_session, other, batch.id) is None


@pytest.mark.asyncio
async def test_get_batch_progress_visible_to_root_admin(db_session):
    owner = User(id=uuid.uuid4(), email="owner3@smu.edu.sg", role=UserRoleEnum.instructor)
    admin = User(id=uuid.uuid4(), email="admin@smu.edu.sg", role=UserRoleEnum.root_admin)
    db_session.add_all([owner, admin])
    await db_session.commit()

    with (
        patch("services.batches_service.download_object", return_value=GOOD_CSV),
        patch("services.batches_service.enqueue_row"),
    ):
        batch = await create_batch(
            db_session,
            actor_id=owner.id,
            upload_key="batches/fake-key.csv",
            file_name="answers.csv",
            strictness="standard",
            retain_answer=True,
            column_mapping=None,
            requires_question_text=False,
        )

    progress = await get_batch_progress(db_session, admin, batch.id)
    assert progress is not None
    assert progress["batch"].id == batch.id


@pytest.mark.asyncio
async def test_cancel_batch_sets_cancelled_at_once(db_session):
    user = User(id=uuid.uuid4(), email="instr3@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()

    with (
        patch("services.batches_service.download_object", return_value=GOOD_CSV),
        patch("services.batches_service.enqueue_row"),
    ):
        batch = await create_batch(
            db_session,
            actor_id=user.id,
            upload_key="batches/fake-key.csv",
            file_name="answers.csv",
            strictness="standard",
            retain_answer=True,
            column_mapping=None,
            requires_question_text=False,
        )

    assert batch.cancelled_at is None

    with patch("services.batches_service.purge_batch_messages") as mock_purge:
        cancelled = await cancel_batch(db_session, user, batch.id)
    assert cancelled.cancelled_at is not None
    first_timestamp = cancelled.cancelled_at
    mock_purge.assert_called_once_with(str(batch.id))

    # Idempotent - cancelling again doesn't move the timestamp, and doesn't
    # re-drain a queue that was already drained.
    with patch("services.batches_service.purge_batch_messages") as mock_purge_again:
        cancelled_again = await cancel_batch(db_session, user, batch.id)
    assert cancelled_again.cancelled_at == first_timestamp
    mock_purge_again.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_batch_none_for_other_actor(db_session):
    owner = User(id=uuid.uuid4(), email="owner2@smu.edu.sg", role=UserRoleEnum.instructor)
    other = User(id=uuid.uuid4(), email="other2@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add_all([owner, other])
    await db_session.commit()

    with (
        patch("services.batches_service.download_object", return_value=GOOD_CSV),
        patch("services.batches_service.enqueue_row"),
    ):
        batch = await create_batch(
            db_session,
            actor_id=owner.id,
            upload_key="batches/fake-key.csv",
            file_name="answers.csv",
            strictness="standard",
            retain_answer=True,
            column_mapping=None,
            requires_question_text=False,
        )

    with patch("services.batches_service.purge_batch_messages") as mock_purge:
        assert await cancel_batch(db_session, other, batch.id) is None
    mock_purge.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_batch_allowed_for_root_admin(db_session):
    owner = User(id=uuid.uuid4(), email="owner4@smu.edu.sg", role=UserRoleEnum.instructor)
    admin = User(id=uuid.uuid4(), email="admin2@smu.edu.sg", role=UserRoleEnum.root_admin)
    db_session.add_all([owner, admin])
    await db_session.commit()

    with (
        patch("services.batches_service.download_object", return_value=GOOD_CSV),
        patch("services.batches_service.enqueue_row"),
    ):
        batch = await create_batch(
            db_session,
            actor_id=owner.id,
            upload_key="batches/fake-key.csv",
            file_name="answers.csv",
            strictness="standard",
            retain_answer=True,
            column_mapping=None,
            requires_question_text=False,
        )

    with patch("services.batches_service.purge_batch_messages") as mock_purge:
        cancelled = await cancel_batch(db_session, admin, batch.id)
    assert cancelled is not None
    assert cancelled.cancelled_at is not None
    mock_purge.assert_called_once_with(str(batch.id))
