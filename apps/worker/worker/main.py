"""SQS poll loop. Thin dispatch shell only - if this file starts containing
threshold/verdict logic, that policy has escaped checks_service and needs to
move back.
"""

import asyncio
import json
import logging
import uuid

import boto3
from config import AWS_ENDPOINT_URL, AWS_REGION, SQS_BATCHES_DLQ_URL, SQS_BATCHES_QUEUE_URL, configure_logging
from db import async_session
from models import Batch, BatchRowFailure
from services import create_check
from sqlalchemy import select

logger = logging.getLogger(__name__)

POLL_WAIT_SECONDS = 20
DLQ_POLL_WAIT_SECONDS = 2


def _sqs_client():
    return boto3.client("sqs", region_name=AWS_REGION, endpoint_url=AWS_ENDPOINT_URL)


async def process_message(db, payload: dict) -> None:
    """Calls the exact domain-logic function the sync route calls. Any
    exception here must propagate - letting the SQS message stay unacked is
    what lets visibility-timeout redelivery and DLQ redrive do their job.

    Checked per-message rather than filtered at enqueue time: cancelling a
    batch never tries to purge messages already sitting in SQS, it just
    makes every row still in flight resolve as a failure instead of a score
    once the Worker gets to it."""
    batch_id = uuid.UUID(payload["batch_id"])
    cancelled_at = (
        await db.execute(select(Batch.cancelled_at).where(Batch.id == batch_id))
    ).scalar_one_or_none()
    if cancelled_at is not None:
        db.add(
            BatchRowFailure(
                id=uuid.uuid4(),
                batch_id=batch_id,
                row_number=0,
                external_ref=payload.get("external_ref"),
                reason="Batch cancelled by instructor.",
            )
        )
        await db.commit()
        return

    await create_check(
        db,
        actor_id=uuid.UUID(payload["actor_id"]),
        answer_text=payload["answer_text"],
        question_text=payload.get("question_text"),
        external_ref=payload["external_ref"],
        strictness=payload["strictness"],
        retain_answer=payload["retain_answer"],
        batch_id=batch_id,
        batch_file_name=None,
    )


async def drain_dlq_once(db) -> int:
    """Messages here have already exhausted SQS's own redelivery attempts
    (the queue's redrive policy routes them here after max-receive-count).
    Recorded as a batch_row_failure so GET /api/batches/{id} shows a
    processing failure as `failed`, not silently stuck `pending` forever -
    see spec Error handling section."""
    response = _sqs_client().receive_message(
        QueueUrl=SQS_BATCHES_DLQ_URL,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=DLQ_POLL_WAIT_SECONDS,
    )
    messages = response.get("Messages", [])
    for message in messages:
        payload = json.loads(message["Body"])
        db.add(
            BatchRowFailure(
                id=uuid.uuid4(),
                batch_id=uuid.UUID(payload["batch_id"]),
                row_number=0,
                external_ref=payload.get("external_ref"),
                reason="Detector processing failed after repeated retries.",
            )
        )
        await db.commit()
        _sqs_client().delete_message(QueueUrl=SQS_BATCHES_DLQ_URL, ReceiptHandle=message["ReceiptHandle"])
    return len(messages)


async def poll_once() -> None:
    response = _sqs_client().receive_message(
        QueueUrl=SQS_BATCHES_QUEUE_URL,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=POLL_WAIT_SECONDS,
    )
    messages = response.get("Messages", [])
    for message in messages:
        payload = json.loads(message["Body"])
        async with async_session() as db:
            try:
                await process_message(db, payload)
            except Exception:
                logger.exception("Failed to process batch row for batch_id=%s", payload.get("batch_id"))
                continue
        _sqs_client().delete_message(
            QueueUrl=SQS_BATCHES_QUEUE_URL, ReceiptHandle=message["ReceiptHandle"]
        )

    async with async_session() as db:
        drained = await drain_dlq_once(db)
        if drained:
            logger.info("Drained %d message(s) from the batches DLQ.", drained)


async def run_forever() -> None:
    logger.info("Worker started, polling %s", SQS_BATCHES_QUEUE_URL)
    while True:
        await poll_once()


def main() -> None:
    configure_logging()
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
