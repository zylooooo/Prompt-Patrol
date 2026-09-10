import json
from unittest.mock import MagicMock, patch

from services.aws_clients import (
    MAX_CANCEL_DRAIN_ITERATIONS,
    enqueue_row,
    generate_upload_url,
    purge_batch_messages,
)


def test_generate_upload_url_returns_url_and_key():
    fake_s3 = MagicMock()
    fake_s3.generate_presigned_url.return_value = "https://example.com/put"

    with patch("services.aws_clients._s3_presign_client", return_value=fake_s3):
        url, key = generate_upload_url("answers.csv")

    assert url == "https://example.com/put"
    assert key.endswith("answers.csv")
    fake_s3.generate_presigned_url.assert_called_once()
    assert fake_s3.generate_presigned_url.call_args.kwargs["ClientMethod"] == "put_object"


def test_enqueue_row_sends_json_body():
    fake_sqs = MagicMock()

    with patch("services.aws_clients._sqs_client", return_value=fake_sqs):
        enqueue_row({"answer_text": "hello world this is long enough"})

    fake_sqs.send_message.assert_called_once()
    assert "MessageBody" in fake_sqs.send_message.call_args.kwargs


def _sqs_message(batch_id: str, receipt: str) -> dict:
    return {"Body": json.dumps({"batch_id": batch_id}), "ReceiptHandle": receipt}


def test_purge_batch_messages_deletes_matches_and_leaves_others_alone():
    """Regression test: an earlier version called ChangeMessageVisibility(0)
    on a non-match to put it straight back as visible, which let this same
    loop immediately re-receive it - a few iterations of that tripped the
    queue's maxReceiveCount redrive policy and silently exiled another
    batch's still-good messages to the DLQ. Verified against real LocalStack
    while fixing it - see openapi.yaml DECISION LOG [0.15.0]."""
    fake_sqs = MagicMock()
    fake_sqs.receive_message.side_effect = [
        {
            "Messages": [
                _sqs_message("target", "r1"),
                _sqs_message("other", "r2"),
            ]
        },
        {"Messages": []},
    ]

    with patch("services.aws_clients._sqs_client", return_value=fake_sqs):
        removed = purge_batch_messages("target")

    assert removed == 1
    fake_sqs.delete_message.assert_called_once_with(
        QueueUrl=fake_sqs.delete_message.call_args.kwargs["QueueUrl"], ReceiptHandle="r1"
    )
    fake_sqs.change_message_visibility.assert_not_called()


def test_purge_batch_messages_stops_at_the_iteration_cap():
    fake_sqs = MagicMock()
    fake_sqs.receive_message.return_value = {"Messages": [_sqs_message("other", "r")]}

    with patch("services.aws_clients._sqs_client", return_value=fake_sqs):
        removed = purge_batch_messages("target")

    assert removed == 0
    assert fake_sqs.receive_message.call_count == MAX_CANCEL_DRAIN_ITERATIONS
