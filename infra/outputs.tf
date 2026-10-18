output "batches_queue_url" {
  value = aws_sqs_queue.batches.url
}

output "batches_queue_arn" {
  value = aws_sqs_queue.batches.arn
}

output "batches_dlq_url" {
  value = aws_sqs_queue.batches_dlq.url
}

output "batches_dlq_arn" {
  value = aws_sqs_queue.batches_dlq.arn
}

output "batches_bucket_name" {
  value = aws_s3_bucket.batches.bucket
}

output "batches_bucket_arn" {
  value = aws_s3_bucket.batches.arn
}

output "secret_arns" {
  value = { for k, s in aws_secretsmanager_secret.app : k => s.arn }
}

output "database_security_group_id" {
  value = aws_security_group.database.id
}
