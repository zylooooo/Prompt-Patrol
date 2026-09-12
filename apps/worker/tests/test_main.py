import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from models import Batch, BatchRowFailure, StrictnessEnum, User, UserRoleEnum
from sqlalchemy import select
from worker.main import drain_dlq_once, poll_once, process_message


@pytest.mark.asyncio
async def test_process_message_calls_create_check(db_session):
    payload = {
        "batch_id": str(uuid.uuid4()),
        "actor_id": str(uuid.uuid4()),
        "strictness": "standard",
        "retain_answer": True,
        "external_ref": "stu-1",
        "answer_text": "This is a long enough answer to be scored properly.",
        "question_text": None,
    }

    with patch("worker.main.create_check", new=AsyncMock()) as mock_create_check:
        await process_message(db_session, payload)

    mock_create_check.assert_called_once()
    kwargs = mock_create_check.call_args.kwargs
    assert kwargs["batch_id"] == uuid.UUID(payload["batch_id"])
    assert kwargs["actor_id"] == uuid.UUID(payload["actor_id"])
    assert kwargs["external_ref"] == "stu-1"


@pytest.mark.asyncio
async def test_process_message_skips_scoring_for_a_cancelled_batch(db_session):
    user = User(id=uuid.uuid4(), email="w2@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    batch = Batch(
        id=uuid.uuid4(),
        actor_id=user.id,
        batch_file_name="a.csv",
        strictness=StrictnessEnum.standard,
        retain_answer=True,
        requires_question_text=False,
        row_total=1,
        cancelled_at=datetime.now(UTC),
    )
    db_session.add(batch)
    await db_session.commit()

    payload = {
        "batch_id": str(batch.id),
        "actor_id": str(user.id),
        "strictness": "standard",
        "retain_answer": True,
        "external_ref": "stu-1",
        "answer_text": "This is a long enough answer to be scored properly.",
        "question_text": None,
    }

    with patch("worker.main.create_check", new=AsyncMock()) as mock_create_check:
        await process_message(db_session, payload)

    mock_create_check.assert_not_called()
    failure = (
        await db_session.execute(select(BatchRowFailure).where(BatchRowFailure.batch_id == batch.id))
    ).scalar_one()
    assert failure.external_ref == "stu-1"
    assert "cancelled" in failure.reason.lower()


@pytest.mark.asyncio
async def test_poll_once_removes_a_cancelled_batchs_message_from_the_queue(db_session):
    """Cancelling never purges SQS directly (see openapi.yaml DECISION LOG
    [0.14.0]) - it relies on poll_once deleting every message it receives,
    scored or skipped, so a cancelled batch's backlog still drains out of
    the queue as the Worker's normal loop reaches each message."""
    user = User(id=uuid.uuid4(), email="w3@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    batch = Batch(
        id=uuid.uuid4(),
        actor_id=user.id,
        batch_file_name="a.csv",
        strictness=StrictnessEnum.standard,
        retain_answer=True,
        requires_question_text=False,
        row_total=1,
        cancelled_at=datetime.now(UTC),
    )
    db_session.add(batch)
    await db_session.commit()

    message = {
        "Body": json.dumps(
            {
                "batch_id": str(batch.id),
                "external_ref": "stu-1",
                "answer_text": "x",
                "actor_id": str(user.id),
                "strictness": "standard",
                "retain_answer": True,
                "question_text": None,
            }
        ),
        "ReceiptHandle": "fake-handle",
    }
    fake_sqs = MagicMock()
    fake_sqs.receive_message.side_effect = [
        {"Messages": [message]},
        {"Messages": []},
    ]

    @asynccontextmanager
    async def fake_async_session():
        yield db_session

    with (
        patch("worker.main._sqs_client", return_value=fake_sqs),
        patch("worker.main.async_session", fake_async_session),
    ):
        await poll_once()

    fake_sqs.delete_message.assert_called_once()
    assert fake_sqs.delete_message.call_args.kwargs["ReceiptHandle"] == "fake-handle"
    failure = (
        await db_session.execute(select(BatchRowFailure).where(BatchRowFailure.batch_id == batch.id))
    ).scalar_one()
    assert "cancelled" in failure.reason.lower()


@pytest.mark.asyncio
async def test_process_message_propagates_detector_failure(db_session):
    """A failed scoring attempt must not be swallowed here - letting it
    propagate is what leaves the SQS message unacked so redelivery/DLQ can
    do their job. See spec Error handling section."""
    payload = {
        "batch_id": str(uuid.uuid4()),
        "actor_id": str(uuid.uuid4()),
        "strictness": "standard",
        "retain_answer": True,
        "external_ref": "stu-1",
        "answer_text": "This is a long enough answer to be scored properly.",
        "question_text": None,
    }

    with patch("worker.main.create_check", new=AsyncMock(side_effect=RuntimeError("boom"))):
        with pytest.raises(RuntimeError):
            await process_message(db_session, payload)


@pytest.mark.asyncio
async def test_drain_dlq_once_writes_batch_row_failure(db_session):
    user = User(id=uuid.uuid4(), email="w@smu.edu.sg", role=UserRoleEnum.instructor)
    db_session.add(user)
    await db_session.commit()
    batch = Batch(
        id=uuid.uuid4(),
        actor_id=user.id,
        batch_file_name="a.csv",
        strictness=StrictnessEnum.standard,
        retain_answer=True,
        requires_question_text=False,
        row_total=1,
    )
    db_session.add(batch)
    await db_session.commit()

    dlq_message = {
        "Body": json.dumps(
            {
                "batch_id": str(batch.id),
                "external_ref": "stu-1",
                "answer_text": "x",
                "actor_id": str(user.id),
                "strictness": "standard",
                "retain_answer": True,
                "question_text": None,
            }
        ),
        "ReceiptHandle": "fake-handle",
    }
    fake_sqs = MagicMock()
    fake_sqs.receive_message.return_value = {"Messages": [dlq_message]}

    with patch("worker.main._sqs_client", return_value=fake_sqs):
        written = await drain_dlq_once(db_session)

    assert written == 1
    failure = (
        await db_session.execute(select(BatchRowFailure).where(BatchRowFailure.batch_id == batch.id))
    ).scalar_one()
    assert failure.external_ref == "stu-1"
    assert "retries" in failure.reason
    fake_sqs.delete_message.assert_called_once()
