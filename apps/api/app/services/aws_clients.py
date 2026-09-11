"""boto3 seam for S3 (presigned batch upload) and SQS (row dispatch to the
Worker). Kept separate from batches_service.py for the same reason
detector_client.py is separate from checks_service.py: this owns *how we
reach AWS*, not the policy of what a valid batch row is.

AWS_ENDPOINT_URL points these clients at LocalStack locally and at nothing
(real AWS) in every other environment - the calls below are otherwise
identical, so there is no "if local" branch anywhere in this file.
"""

import json
import uuid

import boto3

from config import (
    AWS_ENDPOINT_URL,
    AWS_ENDPOINT_URL_PUBLIC,
    AWS_REGION,
    S3_BATCHES_BUCKET,
    SQS_BATCHES_QUEUE_URL,
)

UPLOAD_URL_EXPIRY_SECONDS = 900
# Receive-batches-of-10 iterations to try before giving up on draining a
# cancelled batch's own messages out of SQS - bounds a cancel request
# against a queue full of *other* batches' messages. Anything left behind
# still gets skipped by the Worker's per-message cancelled_at check (see
# openapi.yaml DECISION LOG [0.15.0]), so this is a best-effort speedup,
# not the correctness guarantee.
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
    actor_id (so create_batch can reject a key another instructor generated -
    see batches_service.create_batch) and by a fresh uuid so two instructors
    uploading "answers.csv" the same minute never collide."""
    key = f"batches/{actor_id}/{uuid.uuid4()}-{file_name}"
    url = _s3_presign_client().generate_presigned_url(
        ClientMethod="put_object",
        Params={"Bucket": S3_BATCHES_BUCKET, "Key": key, "ContentType": "text/csv"},
        ExpiresIn=UPLOAD_URL_EXPIRY_SECONDS,
    )
    return url, key


def download_object(key: str) -> str:
    """Pulls the raw CSV bytes back from S3 for the authoritative server-side
    parse - see spec Decision 3's two-layer parsing."""
    body = _s3_client().get_object(Bucket=S3_BATCHES_BUCKET, Key=key)["Body"]
    return body.read().decode("utf-8")


def enqueue_row(payload: dict) -> None:
    """One SQS message per valid CSV row. Payload carries the row's full
    data, not a check_id - see spec Decision 2 (checks are never created
    pending, so there is no row for the Worker to look up by id)."""
    _sqs_client().send_message(QueueUrl=SQS_BATCHES_QUEUE_URL, MessageBody=json.dumps(payload))


def purge_batch_messages(batch_id: str) -> int:
    """Best-effort active drain, run once when a batch is cancelled. SQS has
    no server-side "delete where batch_id=X" - this receives messages 10 at
    a time and deletes the ones belonging to this batch. Messages for other
    batches are left untouched (not deleted, not re-released) - each is
    simply invisible to the Worker for the queue's normal VisibilityTimeout
    before becoming receivable again, same as if this scan had never
    happened. Earlier this called ChangeMessageVisibility(0) to put a
    non-matching message straight back as visible, so the *next* iteration
    of this same loop would immediately receive it again - a few iterations
    of that was enough to trip the queue's maxReceiveCount redrive policy
    and silently exile another batch's still-good rows to the DLQ. Doing
    nothing to a non-match means this loop naturally terminates once it has
    seen every currently-visible message exactly once. See openapi.yaml
    DECISION LOG [0.15.0] for why this is bounded rather than looped until
    the queue is provably empty, and why the Worker's per-message check
    stays the correctness backstop for anything left behind."""
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
            payload = json.loads(message["Body"])
            if payload.get("batch_id") == batch_id:
                client.delete_message(
                    QueueUrl=SQS_BATCHES_QUEUE_URL, ReceiptHandle=message["ReceiptHandle"]
                )
                removed += 1
    return removed
