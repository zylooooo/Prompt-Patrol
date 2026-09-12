import json
import logging
import uuid

import boto3

from config import (
    AWS_ENDPOINT_URL,
    AWS_ENDPOINT_URL_PUBLIC,
    AWS_REGION,
    S3_BATCHES_BUCKET,
    SQS_BATCHES_QUEUE_URL,
)

logger = logging.getLogger(__name__)

UPLOAD_URL_EXPIRY_SECONDS = 900
# Number of retires to drain the SQS of a cancelled batch's own messages.
# Each iteration receives up to 10 messages, so this is 2000 messages max.
# This is a best-effort cleanup, does not guarantee correctness.
MAX_CANCEL_DRAIN_ITERATIONS = 200


def _s3_client():
    return boto3.client("s3", region_name=AWS_REGION, endpoint_url=AWS_ENDPOINT_URL)


def _s3_presign_client():
    """A presigned PUT URL is followed by the browser, so it must be signed
    against a host the browser can reach - LocalStack's in-network hostname
    isn't. Real AWS never sets either endpoint var, so this is the same
    client as _s3_client() there."""
    return boto3.client(
        "s3", region_name=AWS_REGION, endpoint_url=AWS_ENDPOINT_URL_PUBLIC
    )


def _sqs_client():
    return boto3.client("sqs", region_name=AWS_REGION, endpoint_url=AWS_ENDPOINT_URL)


def generate_upload_url(file_name: str, actor_id: uuid.UUID) -> tuple[str, str]:
    """A presigned PUT URL the SPA uploads the raw CSV to directly, plus the
    object key to reference on POST /api/batches. The key is namespaced by
    actor_id to prevent IDOR and by a fresh uuid so two instructors
    uploading "answers.csv" the same minute never collide."""
    key = f"batches/{actor_id}/{uuid.uuid4()}-{file_name}"
    url = _s3_presign_client().generate_presigned_url(
        ClientMethod="put_object",
        Params={"Bucket": S3_BATCHES_BUCKET, "Key": key, "ContentType": "text/csv"},
        ExpiresIn=UPLOAD_URL_EXPIRY_SECONDS,
    )
    return url, key


def download_object(key: str) -> str:
    """Pulls the raw CSV bytes back from S3 for server-side csv parsing."""
    body = _s3_client().get_object(Bucket=S3_BATCHES_BUCKET, Key=key)["Body"]
    return body.read().decode("utf-8")


def enqueue_row(payload: dict) -> None:
    """One SQS message per valid CSV row. Payload carries the row's full
    data, not a check_id."""
    _sqs_client().send_message(QueueUrl=SQS_BATCHES_QUEUE_URL, MessageBody=json.dumps(payload))


def purge_batch_messages(batch_id: str) -> int:
    """Best-effort drain, run once when a batch is cancelled. SQS has no
    server-side "delete where batch_id=X", so this receives 10 at a time and
    deletes only the ones belonging to this batch.

    A non-matching message is left completely alone, not deleted, not
    reset visible. A message with unparsable JSON is skipped the same way - one poison
    message anywhere in the shared queue shouldn't be able to fail every
    instructor's cancel request. The Worker's own per-message cancelled_at check 
    is the correctness backstop for whatever this misses."""
    client = _sqs_client()
    removed = 0
    for _ in range(MAX_CANCEL_DRAIN_ITERATIONS):
        response = client.receive_message(
            QueueUrl=SQS_BATCHES_QUEUE_URL, MaxNumberOfMessages=10, WaitTimeSeconds=0
        )
        messages = response.get("Messages", [])
        if not messages:
            break
        for message in messages:
            try:
                payload = json.loads(message["Body"])
            except json.JSONDecodeError:
                logger.exception("Skipping unparsable message during batch purge.")
                continue
            if payload.get("batch_id") == batch_id:
                client.delete_message(
                    QueueUrl=SQS_BATCHES_QUEUE_URL, ReceiptHandle=message["ReceiptHandle"]
                )
                removed += 1
    return removed
