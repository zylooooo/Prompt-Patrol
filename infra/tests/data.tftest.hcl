# Offline (mock provider). Guards the queue settings that DECISION LOG [0.29.0]
# fixes, and that the CSV bucket stays private and expiring.
mock_provider "aws" {}

run "running" {
  command = apply
  variables { paused = false }

  assert {
    condition     = aws_sqs_queue.batches.visibility_timeout_seconds == 600 && jsondecode(aws_sqs_queue.batches.redrive_policy).maxReceiveCount == 5
    error_message = "Main queue: 600 s visibility and maxReceiveCount 5 (DECISION LOG [0.29.0])."
  }
  assert {
    condition     = aws_sqs_queue.batches_dlq.message_retention_seconds == 1209600
    error_message = "DLQ keeps messages 14 days."
  }
  assert {
    condition     = aws_s3_bucket_lifecycle_configuration.batches.rule[0].expiration[0].days == 60
    error_message = "CSVs expire after 60 days (provisional, PDPA)."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.batches.block_public_acls && aws_s3_bucket_public_access_block.batches.block_public_policy && aws_s3_bucket_public_access_block.batches.ignore_public_acls && aws_s3_bucket_public_access_block.batches.restrict_public_buckets
    error_message = "The CSV bucket must block all public access."
  }
  assert {
    condition     = length(aws_secretsmanager_secret.app) == 8 && alltrue([for k, s in aws_secretsmanager_secret.app : s.name == "prompt-patrol/${k}" && s.recovery_window_in_days == 0])
    error_message = "8 secrets named prompt-patrol/<ENV_VAR>, recovery window 0."
  }
  assert {
    condition     = length(aws_db_instance.main) == 1 && length(aws_secretsmanager_secret_version.db_url) == 1
    error_message = "Running: one DB and a DB_URL written for it."
  }
  assert {
    condition     = !aws_db_instance.main[0].publicly_accessible && aws_db_instance.main[0].storage_encrypted && !aws_db_instance.main[0].multi_az && !aws_db_instance.main[0].deletion_protection
    error_message = "DB: private, encrypted, single-AZ, deletion protection off by default."
  }
  assert {
    condition     = length(aws_security_group.database.ingress) == 0
    error_message = "DB SG starts with no ingress; step 5 adds the task SGs."
  }
}

run "paused" {
  command = apply
  variables { paused = true }

  assert {
    condition     = aws_sqs_queue.batches.name == "prompt-patrol-batches" && aws_s3_bucket.batches.bucket == "prompt-patrol-batches-420974348257"
    error_message = "Queues and bucket are free and must survive a pause."
  }
  assert {
    condition     = length(aws_db_instance.main) + length(aws_secretsmanager_secret_version.db_url) == 0 && length(aws_secretsmanager_secret.app) == 8
    error_message = "Paused: no DB and no DB_URL version, but all 8 secrets stay."
  }
}

run "demo_build" {
  command = apply
  variables {
    paused                 = false
    db_deletion_protection = true
  }
  assert {
    condition     = aws_db_instance.main[0].deletion_protection
    error_message = "db_deletion_protection must reach the instance."
  }
}

run "pause_blocked_by_deletion_protection" {
  command = plan
  variables {
    paused                 = true
    db_deletion_protection = true
  }
  expect_failures = [var.paused]
}
