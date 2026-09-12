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
POLL_MAX_MESSAGES = 10
DLQ_POLL_WAIT_SECONDS = 0


_sqs = boto3.client("sqs", region_name=AWS_REGION, endpoint_url=AWS_ENDPOINT_URL)


def _sqs_client():
    return _sqs


async def process_message(db, payload: dict) -> None:
    """Calls the exact domain-logic function the sync route calls. Any
    exception here must propagate. Letting the SQS message stay unacked is
    what lets visibility-timeout redelivery and DLQ redrive do their job.

    Every messsage in the queue is checked at view time to see if the batch
    has been cancelled. This is a safety guardrail to ensure that if the batch
    is cancelled, the answer will not be processed and will be recorded as a
    failure with a reason. This is purely a safety guardrail. When the batch is
    cancelled by the user, a backend call will purge all messgaes in the queue
    for that batch. This guardrail is to ensure that any messages left after the
    purge will not be processed by chance."""
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
    processing failure as `failed`, not silently stuck `pending` forever.

    WaitTimeSeconds=0: this is a side pass piggybacked onto every poll_once
    call, not the main loop's purpose - a blocking long-poll here would tax
    every main-queue cycle with a wait for a queue that's usually empty."""
    response = await asyncio.to_thread(
        _sqs_client().receive_message,
        QueueUrl=SQS_BATCHES_DLQ_URL,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=DLQ_POLL_WAIT_SECONDS,
    )
    messages = response.get("Messages", [])
    for message in messages:
        try:
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
        except Exception:
            logger.exception("Failed to record DLQ message as a batch row failure.")
            continue
        await asyncio.to_thread(
            _sqs_client().delete_message, QueueUrl=SQS_BATCHES_DLQ_URL, ReceiptHandle=message["ReceiptHandle"]
        )
    return len(messages)


async def poll_once() -> None:
    """One main-queue pass (up to POLL_MAX_MESSAGES at once, so a full batch
    upload doesn't pay one 20s long-poll round trip per row) then one DLQ
    drain pass, always in that order. A failed row is left on the queue (no
    delete) rather than moved to the DLQ here - that's SQS's own redrive
    policy's job after maxReceiveCount, not ours to short-circuit."""
    response = await asyncio.to_thread(
        _sqs_client().receive_message,
        QueueUrl=SQS_BATCHES_QUEUE_URL,
        MaxNumberOfMessages=POLL_MAX_MESSAGES,
        WaitTimeSeconds=POLL_WAIT_SECONDS,
    )
    messages = response.get("Messages", [])
    for message in messages:
        try:
            payload = json.loads(message["Body"])
            async with async_session() as db:
                await process_message(db, payload)
        except Exception:
            logger.exception("Failed to process batch row: %s", message.get("Body"))
            continue
        await asyncio.to_thread(
            _sqs_client().delete_message,
            QueueUrl=SQS_BATCHES_QUEUE_URL,
            ReceiptHandle=message["ReceiptHandle"],
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
