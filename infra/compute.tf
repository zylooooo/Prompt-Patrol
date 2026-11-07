# Fargate foundation for the api, worker and detector: cluster, IAM, SGs, log
# groups and detector discovery. All free, so none of it follows var.paused;
# the task definitions and services that use it do.
# Every resource is written out per service on purpose each one can be read 
# and changed on its own.

# --- Cluster -----------------------------------------------------------------

# Container Insights costs extra; the basic per-service CPU/memory metrics are free.
resource "aws_ecs_cluster" "main" {
  name = "prompt-patrol"

  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

# --- Logs --------------------------------------------------------------------

# 14 days: enough to debug a test window; emails are redacted outside dev.
resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/prompt-patrol/api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/prompt-patrol/worker"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "detector" {
  name              = "/ecs/prompt-patrol/detector"
  retention_in_days = 14
}

# --- Detector discovery ------------------------------------------------------

# Plain Cloud Map DNS, not Service Connect: no Envoy sidecar, nothing new to
# reach from the internet-less isolated subnets. The private zone is ~$0.50/month.
resource "aws_service_discovery_private_dns_namespace" "main" {
  name = "prompt-patrol.internal"
  vpc  = aws_vpc.main.id
}

# detector.prompt-patrol.internal. The custom health check lets ECS report the
# container health check, so a detector still loading its model gets no traffic.
resource "aws_service_discovery_service" "detector" {
  name = "detector"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.main.id
    routing_policy = "MULTIVALUE"

    dns_records {
      type = "A"
      ttl  = 10
    }
  }

  # An empty block is never sent to AWS, so every plan wants to replace the
  # service. failure_threshold is deprecated (AWS always uses 1) but makes the
  # provider send the block.
  health_check_custom_config {
    failure_threshold = 1
  }

  # ECS registers the detector task here; without this a replacement fails
  # with ResourceInUse.
  force_destroy = true
}

# --- IAM ---------------------------------------------------------------------

# aws:SourceAccount: only ECS acting for this account can assume these roles
# (confused-deputy guard). Same trust for all three roles.
locals {
  ecs_tasks_trust = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = "420974348257" } }
    }]
  })
}

# Used by ECS itself to start every task: ECR pull, log streams, secret injection.
resource "aws_iam_role" "execution" {
  name               = "prompt-patrol-ecs-execution"
  description        = "ECS task execution: image pull, logs, secrets injection"
  assume_role_policy = local.ecs_tasks_trust
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The 8 app secrets only. AWS-managed key, so no kms:Decrypt needed.
resource "aws_iam_role_policy" "execution_secrets" {
  name = "app-secrets"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = [for s in aws_secretsmanager_secret.app : s.arn]
    }]
  })
}

resource "aws_iam_role" "api_task" {
  name               = "prompt-patrol-api-task"
  description        = "API task: batch CSVs in S3, enqueue + cancel-drain on SQS"
  assume_role_policy = local.ecs_tasks_trust
}

# Matches apps/api/app/services/aws_clients.py: presigned put_object, get_object,
# send_message, and the cancel drain's receive_message/delete_message.
resource "aws_iam_role_policy" "api_task" {
  name = "batches"
  role = aws_iam_role.api_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "BatchCsvs"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.batches.arn}/batches/*"
      },
      {
        # Without ListBucket S3 answers a missing key with 403, not NoSuchKey,
        # and download_object's FileNotFoundError branch never fires. No
        # s3:prefix condition: that implicit check carries no prefix. The
        # bucket holds only batch CSVs, so listing widens nothing real.
        Sid      = "BatchCsvsNotFound"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.batches.arn
      },
      {
        Sid      = "BatchQueue"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage"]
        Resource = aws_sqs_queue.batches.arn
      },
    ]
  })
}

resource "aws_iam_role" "worker_task" {
  name               = "prompt-patrol-worker-task"
  description        = "Worker task: consume the batch queue and its DLQ"
  assume_role_policy = local.ecs_tasks_trust
}

# Matches apps/worker/worker/main.py: receive/delete on both queues, no S3.
resource "aws_iam_role_policy" "worker_task" {
  name = "batches"
  role = aws_iam_role.worker_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "BatchQueues"
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage"]
      Resource = [aws_sqs_queue.batches.arn, aws_sqs_queue.batches_dlq.arn]
    }]
  })
}

# The detector has no task role: it calls no AWS API.

# --- Security groups ---------------------------------------------------------
# Rules are separate resources, never inline, so each one is reviewable and the
# database SG (database.tf) stays rule-free in its own block.

resource "aws_security_group" "alb" {
  name        = "prompt-patrol-alb"
  description = "Internal ALB; in from the CloudFront VPC origin only"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "api" {
  name        = "prompt-patrol-api"
  description = "API tasks and one-off tasks; in from the ALB only"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "worker" {
  name        = "prompt-patrol-worker"
  description = "Worker tasks; no inbound"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "detector" {
  name        = "prompt-patrol-detector"
  description = "Detector tasks; in from api and worker only, no internet"
  vpc_id      = aws_vpc.main.id
}

# ALB. Its ingress from CloudFront is added with the VPC origin it depends on.
resource "aws_vpc_security_group_egress_rule" "alb_to_api" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.api.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

# API
resource "aws_vpc_security_group_ingress_rule" "api_from_alb" {
  security_group_id            = aws_security_group.api.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

# Auth0 has no fixed IPs, so the API (and its NAT route) can't be narrowed.
resource "aws_vpc_security_group_egress_rule" "api_all" {
  security_group_id = aws_security_group.api.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# Worker: interface endpoints, ECR layers via the S3 gateway, detector, DB.
resource "aws_vpc_security_group_egress_rule" "worker_https_vpc" {
  security_group_id = aws_security_group.worker.id
  cidr_ipv4         = aws_vpc.main.cidr_block
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "worker_https_s3" {
  security_group_id = aws_security_group.worker.id
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "worker_to_detector" {
  security_group_id            = aws_security_group.worker.id
  referenced_security_group_id = aws_security_group.detector.id
  ip_protocol                  = "tcp"
  from_port                    = 8001
  to_port                      = 8001
}

resource "aws_vpc_security_group_egress_rule" "worker_to_database" {
  security_group_id            = aws_security_group.worker.id
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

# Detector
resource "aws_vpc_security_group_ingress_rule" "detector_from_api" {
  security_group_id            = aws_security_group.detector.id
  referenced_security_group_id = aws_security_group.api.id
  ip_protocol                  = "tcp"
  from_port                    = 8001
  to_port                      = 8001
}

resource "aws_vpc_security_group_ingress_rule" "detector_from_worker" {
  security_group_id            = aws_security_group.detector.id
  referenced_security_group_id = aws_security_group.worker.id
  ip_protocol                  = "tcp"
  from_port                    = 8001
  to_port                      = 8001
}

# Image pull and logs only; the model is baked into the image.
resource "aws_vpc_security_group_egress_rule" "detector_https_vpc" {
  security_group_id = aws_security_group.detector.id
  cidr_ipv4         = aws_vpc.main.cidr_block
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "detector_https_s3" {
  security_group_id = aws_security_group.detector.id
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

# Database (SG in database.tf)
resource "aws_vpc_security_group_ingress_rule" "database_from_api" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.api.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "database_from_worker" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.worker.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

# --- Task definitions --------------------------------------------------------
# Hourly-billed once a service runs them, so all three follow var.paused.

locals {
  api_family   = "prompt-patrol-api"
  detector_url = "http://${aws_service_discovery_service.detector.name}.${aws_service_discovery_private_dns_namespace.main.name}:8001"

  # settings.py refuses to start without all 8, and every importer reads it
  # (api, worker, alembic, scripts). name = env var, valueFrom = the secret.
  app_secrets_env = [for k, s in aws_secretsmanager_secret.app : { name = k, valueFrom = s.arn }]

  # api and worker import the same settings.py, so both need API_HOST/PORT and
  # an https FRONTEND_URL on the redirect URI's host. No AWS_ENDPOINT_URL*:
  # boto3 resolves the real endpoints. Calibration values exactly as in
  # apps/docker-compose.desklib.yml.
  app_env = [for k, v in {
    ENVIRONMENT                  = "prod"
    API_HOST                     = "0.0.0.0"
    API_PORT                     = "8000"
    FRONTEND_URL                 = local.frontend_url
    AWS_REGION                   = "ap-southeast-1"
    S3_BATCHES_BUCKET            = aws_s3_bucket.batches.bucket
    SQS_BATCHES_QUEUE_URL        = aws_sqs_queue.batches.url
    SQS_BATCHES_DLQ_URL          = aws_sqs_queue.batches_dlq.url
    DETECTOR_URL                 = local.detector_url
    LOG_LEVEL                    = "info"
    DETECTOR_MODEL_VERSION       = "desklib-academic-lora-v1"
    DETECTOR_CALIBRATION_VERSION = "desklib-temp1.944-v1"
    # asyncpg verifies the RDS cert against this bundle (DB_URL's ssl=verify-full).
    # Shipped in both images from apps/api/app/certs/.
    PGSSLROOTCERT      = "/app/certs/rds-global-bundle.pem"
    DETECTOR_THRESHOLD = "0.9608"
    ABSTENTION_BAND    = "0.01"
  } : { name = k, value = v }]
}

# Also the one-off task definition: migrations, the session purge and
# provision_user run on it with a command override (see outputs.tf). The
# service's command skips entrypoint.sh, so only the migration task migrates.
resource "aws_ecs_task_definition" "api" {
  count                    = var.paused ? 0 : 1
  family                   = local.api_family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.api_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name         = "api"
    image        = "${aws_ecr_repository.service["api"].repository_url}:${local.image_tag}"
    essential    = true
    command      = ["python", "main.py"]
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment  = local.app_env
    secrets      = local.app_secrets_env
    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = "ap-southeast-1"
        awslogs-stream-prefix = "ecs"
      }
    }
  }])
}

# No port and no health check: it only long-polls SQS, and its image has no curl.
resource "aws_ecs_task_definition" "worker" {
  count                    = var.paused ? 0 : 1
  family                   = "prompt-patrol-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.worker_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name        = "worker"
    image       = "${aws_ecr_repository.service["worker"].repository_url}:${local.image_tag}"
    essential   = true
    environment = local.app_env
    secrets     = local.app_secrets_env
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.worker.name
        awslogs-region        = "ap-southeast-1"
        awslogs-stream-prefix = "ecs"
      }
    }
  }])
}

# No secrets, no task role: text in, score out. DETECTOR_BACKEND=desklib is
# baked into Dockerfile.desklib. The size is a knob: lower it once the
# service's MemoryUtilization shows real use. startPeriod 300 (the ECS
# maximum) covers the model load, as in compose.
resource "aws_ecs_task_definition" "detector" {
  count                    = var.paused ? 0 : 1
  family                   = "prompt-patrol-detector"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "2048"
  memory                   = "8192"
  execution_role_arn       = aws_iam_role.execution.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name         = "detector"
    image        = "${aws_ecr_repository.service["detector"].repository_url}:${local.image_tag}"
    essential    = true
    portMappings = [{ containerPort = 8001, protocol = "tcp" }]
    environment = [
      { name = "DETECTOR_HOST", value = "0.0.0.0" },
      { name = "DETECTOR_PORT", value = "8001" },
    ]
    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8001/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 300
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.detector.name
        awslogs-region        = "ap-southeast-1"
        awslogs-stream-prefix = "ecs"
      }
    }
  }])
}

# --- Services ----------------------------------------------------------------
# One task each, min 100 % / max 200 %: a rollout starts the new task before
# stopping the old one. The circuit breaker rolls back a task that never gets
# healthy. wait_for_steady_state = false: apply returns; the rollout is
# watched in the console or with `aws ecs describe-services`. No ECS Exec.

resource "aws_ecs_service" "api" {
  count                              = var.paused ? 0 : 1
  name                               = "api"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.api[0].arn
  launch_type                        = "FARGATE"
  desired_count                      = 1
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  enable_execute_command             = false
  wait_for_steady_state              = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # Egress subnets: the NAT route to Auth0.
  network_configuration {
    subnets          = aws_subnet.egress[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api[0].arn
    container_name   = "api"
    container_port   = 8000
  }

  # ECS rejects a target group that no load balancer listener uses yet. On
  # resume, tasks must not start before RDS exists and DB_URL holds its new
  # password, or the api stalls and the worker runs on a stale one.
  depends_on = [aws_lb_listener.http, aws_secretsmanager_secret_version.db_url]

  # CD owns rollouts: it registers new revisions and updates the service (spec, option A).
  lifecycle {
    ignore_changes = [task_definition]
  }
}

resource "aws_ecs_service" "worker" {
  count                              = var.paused ? 0 : 1
  name                               = "worker"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.worker[0].arn
  launch_type                        = "FARGATE"
  desired_count                      = 1
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  enable_execute_command             = false
  wait_for_steady_state              = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.isolated[*].id
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = false
  }

  # Same as api: wait for RDS and the new DB_URL on resume.
  depends_on = [aws_secretsmanager_secret_version.db_url]

  # CD owns rollouts: it registers new revisions and updates the service (spec, option A).
  lifecycle {
    ignore_changes = [task_definition]
  }
}

resource "aws_ecs_service" "detector" {
  count                              = var.paused ? 0 : 1
  name                               = "detector"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.detector[0].arn
  launch_type                        = "FARGATE"
  desired_count                      = 1
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  enable_execute_command             = false
  wait_for_steady_state              = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.isolated[*].id
    security_groups  = [aws_security_group.detector.id]
    assign_public_ip = false
  }

  # detector.prompt-patrol.internal -> this task's IP, once healthy.
  service_registries {
    registry_arn = aws_service_discovery_service.detector.arn
  }

  # CD owns rollouts: it registers new revisions and updates the service (spec, option A).
  lifecycle {
    ignore_changes = [task_definition]
  }
}

# --- Session purge -----------------------------------------------------------

# Free, so not paused; the schedule that uses it is.
resource "aws_iam_role" "scheduler" {
  name        = "prompt-patrol-scheduler"
  description = "EventBridge Scheduler: run the session purge on the API task definition"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = "420974348257" } }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "run-purge"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "RunApiTask"
        Effect = "Allow"
        Action = "ecs:RunTask"
        Resource = [
          "arn:aws:ecs:ap-southeast-1:420974348257:task-definition/${local.api_family}",
          "arn:aws:ecs:ap-southeast-1:420974348257:task-definition/${local.api_family}:*",
        ]
      },
      {
        Sid      = "PassApiRoles"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = [aws_iam_role.execution.arn, aws_iam_role.api_task.arn]
      },
    ]
  })
}

# Daily 03:00 Singapore: python -m scripts.purge_sessions on the API task
# definition, egress subnets, API SG (same placement as the one-off commands).
resource "aws_scheduler_schedule" "purge_sessions" {
  count                        = var.paused ? 0 : 1
  name                         = "prompt-patrol-purge-sessions"
  schedule_expression          = "cron(0 3 * * ? *)"
  schedule_expression_timezone = "Asia/Singapore"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn
    input = jsonencode({
      containerOverrides = [{ name = "api", command = ["python", "-m", "scripts.purge_sessions"] }]
    })

    ecs_parameters {
      task_definition_arn = "arn:aws:ecs:ap-southeast-1:420974348257:task-definition/${local.api_family}" # family: latest ACTIVE revision, so CD deploys reach the purge
      launch_type         = "FARGATE"
      task_count          = 1

      network_configuration {
        subnets          = aws_subnet.egress[*].id
        security_groups  = [aws_security_group.api.id]
        assign_public_ip = false
      }
    }
  }
}
