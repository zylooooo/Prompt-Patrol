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

output "frontend_url" {
  value = local.frontend_url
}

# Auth0 Allowed Callback URL and AUTH0_REDIRECT_URI.
output "auth0_callback_url" {
  value = "${local.frontend_url}/api/auth/callback"
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.web.id
}

output "web_bucket_name" {
  value = aws_s3_bucket.web.bucket
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

# One-off tasks on the API task definition (Git Bash). Run them only after a
# rollout has settled: mid-rollout the 6-vCPU Fargate quota is already full.
locals {
  run_api_task = join(" ", [
    "aws ecs run-task --profile prompt-patrol --region ap-southeast-1",
    "--cluster ${aws_ecs_cluster.main.name} --task-definition ${local.api_family} --launch-type FARGATE",
    "--network-configuration 'awsvpcConfiguration={subnets=[${join(",", aws_subnet.egress[*].id)}],securityGroups=[${aws_security_group.api.id}],assignPublicIp=DISABLED}'",
  ])
}

output "migrate_command" {
  value = "${local.run_api_task} --overrides '{\"containerOverrides\":[{\"name\":\"api\",\"command\":[\"alembic\",\"upgrade\",\"head\"]}]}'"
}

# Replace <email> before running. Literal JSON, not jsonencode: that would
# escape the placeholder's angle brackets to unicode escapes.
output "provision_admin_command" {
  value = "${local.run_api_task} --overrides '{\"containerOverrides\":[{\"name\":\"api\",\"command\":[\"python\",\"-m\",\"scripts.provision_user\",\"add\",\"promptpatrol@outlook.com\",\"root_admin\"]}]}'"
}

# PP-533 load generator; null while var.loadtest_enabled is off (or paused).
output "loadtest_instance_id" {
  value = one(aws_instance.loadtest[*].id)
}

output "loadtest_public_ip" {
  value = one(aws_eip.loadtest[*].public_ip)
}

output "loadtest_bucket" {
  value = one(aws_s3_bucket.loadtest_transfer[*].bucket)
}
