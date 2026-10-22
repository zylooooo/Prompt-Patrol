# Batch job queue and its dead-letter queue. Free at rest, so not gated on
# var.paused. 600 s visibility and maxReceiveCount 5 come from the contract,
# change them there first.

resource "aws_sqs_queue" "batches_dlq" {
  name                      = "prompt-patrol-batches-dlq"
  message_retention_seconds = 1209600 # 14 days, the SQS maximum
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "batches" {
  name                       = "prompt-patrol-batches"
  visibility_timeout_seconds = 600
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.batches_dlq.arn
    maxReceiveCount     = 5
  })
}
