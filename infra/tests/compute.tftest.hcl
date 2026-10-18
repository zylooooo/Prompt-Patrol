# Offline (mock provider). Guards who can reach whom on the network and what
# each task role may touch: the parts of step 5 a typo would silently widen.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "running" {
  command = apply
  variables { paused = false }

  # --- Security groups ---------------------------------------------------------

  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.database_from_api.security_group_id == aws_security_group.database.id &&
      aws_vpc_security_group_ingress_rule.database_from_worker.security_group_id == aws_security_group.database.id &&
      alltrue([for r in [aws_vpc_security_group_ingress_rule.database_from_api, aws_vpc_security_group_ingress_rule.database_from_worker] : r.from_port == 5432 && r.to_port == 5432 && r.ip_protocol == "tcp"]) &&
      toset([aws_vpc_security_group_ingress_rule.database_from_api.referenced_security_group_id, aws_vpc_security_group_ingress_rule.database_from_worker.referenced_security_group_id]) == toset([aws_security_group.api.id, aws_security_group.worker.id])
    )
    error_message = "DB SG: 5432 from the api and worker SGs only."
  }
  assert {
    condition     = length(aws_security_group.database.ingress) == 0
    error_message = "DB SG rules must be separate rule resources, never inline."
  }
  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.detector_from_api.security_group_id == aws_security_group.detector.id &&
      aws_vpc_security_group_ingress_rule.detector_from_worker.security_group_id == aws_security_group.detector.id &&
      alltrue([for r in [aws_vpc_security_group_ingress_rule.detector_from_api, aws_vpc_security_group_ingress_rule.detector_from_worker] : r.from_port == 8001 && r.to_port == 8001 && r.ip_protocol == "tcp"]) &&
      toset([aws_vpc_security_group_ingress_rule.detector_from_api.referenced_security_group_id, aws_vpc_security_group_ingress_rule.detector_from_worker.referenced_security_group_id]) == toset([aws_security_group.api.id, aws_security_group.worker.id]) &&
      length(aws_security_group.detector.ingress) == 0
    )
    error_message = "Detector SG: 8001 from the api and worker SGs only."
  }
  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.api_from_alb.security_group_id == aws_security_group.api.id &&
      aws_vpc_security_group_ingress_rule.api_from_alb.referenced_security_group_id == aws_security_group.alb.id &&
      aws_vpc_security_group_ingress_rule.api_from_alb.from_port == 8000 && aws_vpc_security_group_ingress_rule.api_from_alb.to_port == 8000 &&
      aws_vpc_security_group_egress_rule.alb_to_api.security_group_id == aws_security_group.alb.id &&
      aws_vpc_security_group_egress_rule.alb_to_api.referenced_security_group_id == aws_security_group.api.id &&
      aws_vpc_security_group_egress_rule.alb_to_api.from_port == 8000 && aws_vpc_security_group_egress_rule.alb_to_api.to_port == 8000
    )
    error_message = "ALB -> api on 8000, both directions."
  }
  assert {
    condition     = length(aws_security_group.worker.ingress) == 0
    error_message = "Worker SG has no inbound."
  }
  assert {
    condition = (
      aws_vpc_security_group_egress_rule.detector_https_vpc.security_group_id == aws_security_group.detector.id &&
      aws_vpc_security_group_egress_rule.detector_https_vpc.cidr_ipv4 == aws_vpc.main.cidr_block &&
      aws_vpc_security_group_egress_rule.detector_https_s3.prefix_list_id == aws_vpc_endpoint.s3.prefix_list_id &&
      length(aws_security_group.detector.egress) == 0
    )
    error_message = "Detector egress: 443 to the VPC CIDR and the S3 prefix list only (no internet)."
  }
  assert {
    condition     = toset([aws_security_group.alb.name, aws_security_group.api.name, aws_security_group.worker.name, aws_security_group.detector.name]) == toset(["prompt-patrol-alb", "prompt-patrol-api", "prompt-patrol-worker", "prompt-patrol-detector"])
    error_message = "SG names are prompt-patrol-{alb,api,worker,detector}."
  }

  # --- IAM -----------------------------------------------------------------------

  assert {
    condition     = toset(flatten([jsondecode(aws_iam_role_policy.execution_secrets.policy).Statement[0].Resource])) == toset([for s in aws_secretsmanager_secret.app : s.arn]) && jsondecode(aws_iam_role_policy.execution_secrets.policy).Statement[0].Action == "secretsmanager:GetSecretValue"
    error_message = "Execution role reads exactly the 8 app secrets."
  }
  assert {
    condition     = aws_iam_role_policy_attachment.execution_managed.policy_arn == "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy" && aws_iam_role_policy_attachment.execution_managed.role == aws_iam_role.execution.name
    error_message = "Execution role carries the managed ECS task execution policy."
  }
  assert {
    condition = alltrue([for r in [aws_iam_role.execution, aws_iam_role.api_task, aws_iam_role.worker_task] :
      jsondecode(r.assume_role_policy).Statement[0].Principal == { Service = "ecs-tasks.amazonaws.com" } &&
      jsondecode(r.assume_role_policy).Statement[0].Condition == { StringEquals = { "aws:SourceAccount" = "420974348257" } } &&
      length(jsondecode(r.assume_role_policy).Statement) == 1
    ])
    error_message = "ECS roles trust only ecs-tasks.amazonaws.com from this account."
  }
  assert {
    condition = (
      length(jsondecode(aws_iam_role_policy.api_task.policy).Statement) == 3 &&
      toset(jsondecode(aws_iam_role_policy.api_task.policy).Statement[0].Action) == toset(["s3:PutObject", "s3:GetObject"]) &&
      jsondecode(aws_iam_role_policy.api_task.policy).Statement[0].Resource == "${aws_s3_bucket.batches.arn}/batches/*" &&
      jsondecode(aws_iam_role_policy.api_task.policy).Statement[1].Action == "s3:ListBucket" &&
      jsondecode(aws_iam_role_policy.api_task.policy).Statement[1].Resource == aws_s3_bucket.batches.arn &&
      toset(jsondecode(aws_iam_role_policy.api_task.policy).Statement[2].Action) == toset(["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage"]) &&
      jsondecode(aws_iam_role_policy.api_task.policy).Statement[2].Resource == aws_sqs_queue.batches.arn
    )
    error_message = "API task: S3 Put/Get on batches/*, ListBucket on the bucket, SQS Send/Receive/Delete on the main queue only."
  }
  assert {
    condition = (
      length(jsondecode(aws_iam_role_policy.worker_task.policy).Statement) == 1 &&
      toset(jsondecode(aws_iam_role_policy.worker_task.policy).Statement[0].Action) == toset(["sqs:ReceiveMessage", "sqs:DeleteMessage"]) &&
      toset(jsondecode(aws_iam_role_policy.worker_task.policy).Statement[0].Resource) == toset([aws_sqs_queue.batches.arn, aws_sqs_queue.batches_dlq.arn]) &&
      !strcontains(aws_iam_role_policy.worker_task.policy, "s3:")
    )
    error_message = "Worker task: SQS Receive/Delete on main + DLQ, no S3."
  }

  # --- Logs, cluster, discovery --------------------------------------------------

  assert {
    condition = (
      [for g in [aws_cloudwatch_log_group.api, aws_cloudwatch_log_group.worker, aws_cloudwatch_log_group.detector] : g.name] == ["/ecs/prompt-patrol/api", "/ecs/prompt-patrol/worker", "/ecs/prompt-patrol/detector"] &&
      alltrue([for g in [aws_cloudwatch_log_group.api, aws_cloudwatch_log_group.worker, aws_cloudwatch_log_group.detector] : g.retention_in_days == 14])
    )
    error_message = "Three log groups /ecs/prompt-patrol/<svc>, 14-day retention."
  }
  assert {
    condition     = aws_ecs_cluster.main.name == "prompt-patrol" && one([for s in aws_ecs_cluster.main.setting : s.value if s.name == "containerInsights"]) == "disabled"
    error_message = "Cluster prompt-patrol, Container Insights off."
  }
  assert {
    condition = (
      aws_service_discovery_private_dns_namespace.main.name == "prompt-patrol.internal" &&
      aws_service_discovery_service.detector.name == "detector" &&
      aws_service_discovery_service.detector.dns_config[0].dns_records[0].type == "A" &&
      aws_service_discovery_service.detector.dns_config[0].dns_records[0].ttl == 10 &&
      length(aws_service_discovery_service.detector.health_check_custom_config) == 1
    )
    error_message = "detector.prompt-patrol.internal: A record, TTL 10."
  }

  # --- Edge ----------------------------------------------------------------------

  assert {
    condition     = aws_lb.api[0].internal && aws_lb.api[0].name == "prompt-patrol" && toset(aws_lb.api[0].subnets) == toset(aws_subnet.isolated[*].id)
    error_message = "ALB prompt-patrol is internal, in the isolated subnets."
  }
  assert {
    condition = (
      aws_lb_target_group.api[0].target_type == "ip" && aws_lb_target_group.api[0].port == 8000 &&
      aws_lb_target_group.api[0].health_check[0].path == "/health" && aws_lb_target_group.api[0].deregistration_delay == "30" &&
      aws_lb_listener.http[0].port == 80 && aws_lb_listener.http[0].default_action[0].target_group_arn == aws_lb_target_group.api[0].arn
    )
    error_message = "Listener 80 -> target group (ip, 8000, /health, deregistration 30 s)."
  }
  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.alb_from_cloudfront[0].security_group_id == aws_security_group.alb.id &&
      aws_vpc_security_group_ingress_rule.alb_from_cloudfront[0].referenced_security_group_id == data.aws_security_group.cloudfront_vpc_origin[0].id &&
      aws_vpc_security_group_ingress_rule.alb_from_cloudfront[0].from_port == 80 && aws_vpc_security_group_ingress_rule.alb_from_cloudfront[0].to_port == 80 &&
      length(aws_security_group.alb.ingress) == 0
    )
    error_message = "ALB SG: in 80 from the CloudFront VPC-origin SG only."
  }
  assert {
    condition     = aws_cloudfront_vpc_origin.alb[0].vpc_origin_endpoint_config[0].arn == aws_lb.api[0].arn && aws_cloudfront_vpc_origin.alb[0].vpc_origin_endpoint_config[0].origin_protocol_policy == "http-only" && aws_cloudfront_vpc_origin.alb[0].vpc_origin_endpoint_config[0].http_port == 80
    error_message = "VPC origin points at the ALB over HTTP 80."
  }
  assert {
    condition     = length(aws_cloudfront_distribution.web.custom_error_response) == 0 && aws_cloudfront_distribution.web.price_class == "PriceClass_200"
    error_message = "Distribution: no custom_error_response (would mask API 404s), PriceClass_200."
  }
  assert {
    condition = (
      length(aws_cloudfront_distribution.web.ordered_cache_behavior) == 1 &&
      aws_cloudfront_distribution.web.ordered_cache_behavior[0].path_pattern == "/api/*" &&
      aws_cloudfront_distribution.web.ordered_cache_behavior[0].cache_policy_id == data.aws_cloudfront_cache_policy.caching_disabled.id &&
      aws_cloudfront_distribution.web.ordered_cache_behavior[0].origin_request_policy_id == data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id &&
      aws_cloudfront_distribution.web.ordered_cache_behavior[0].viewer_protocol_policy == "redirect-to-https" &&
      one([for o in aws_cloudfront_distribution.web.origin : o.vpc_origin_config[0].origin_read_timeout if o.origin_id == "api"]) == 60
    )
    error_message = "/api/* -> VPC origin: CachingDisabled + AllViewerExceptHostHeader, redirect-to-https, 60 s read timeout."
  }
  assert {
    condition = (
      one([for f in aws_cloudfront_distribution.web.default_cache_behavior[0].function_association : f.function_arn if f.event_type == "viewer-request"]) == aws_cloudfront_function.spa_rewrite.arn &&
      aws_cloudfront_distribution.web.default_cache_behavior[0].cache_policy_id == data.aws_cloudfront_cache_policy.caching_optimized.id &&
      aws_cloudfront_distribution.web.default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https"
    )
    error_message = "Default behavior: SPA rewrite function on viewer-request, CachingOptimized, redirect-to-https."
  }
  assert {
    condition = (
      jsondecode(aws_s3_bucket_policy.web.policy).Statement[1].Principal == { Service = "cloudfront.amazonaws.com" } &&
      jsondecode(aws_s3_bucket_policy.web.policy).Statement[1].Action == "s3:GetObject" &&
      jsondecode(aws_s3_bucket_policy.web.policy).Statement[1].Condition == { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } } &&
      aws_s3_bucket_public_access_block.web.restrict_public_buckets && aws_s3_bucket_public_access_block.web.block_public_policy
    )
    error_message = "SPA bucket: private, readable only by this distribution via OAC."
  }
  assert {
    condition     = output.frontend_url == "https://${aws_cloudfront_distribution.web.domain_name}" && output.auth0_callback_url == "https://${aws_cloudfront_distribution.web.domain_name}/api/auth/callback"
    error_message = "frontend_url / auth0_callback_url come from the distribution domain."
  }

  # --- Services --------------------------------------------------------------------

  assert {
    condition     = length(aws_ecs_service.api) == 1 && length(aws_ecs_service.worker) == 1 && length(aws_ecs_service.detector) == 1
    error_message = "One service each for api, worker, detector."
  }
  assert {
    condition = (
      toset(aws_ecs_service.api[0].network_configuration[0].subnets) == toset(aws_subnet.egress[*].id) &&
      toset(aws_ecs_service.worker[0].network_configuration[0].subnets) == toset(aws_subnet.isolated[*].id) &&
      toset(aws_ecs_service.detector[0].network_configuration[0].subnets) == toset(aws_subnet.isolated[*].id) &&
      alltrue([for s in [aws_ecs_service.api[0], aws_ecs_service.worker[0], aws_ecs_service.detector[0]] : s.network_configuration[0].assign_public_ip == false])
    )
    error_message = "api in egress subnets, worker and detector in isolated, no public IPs."
  }
  assert {
    condition = (
      length(aws_ecs_service.api[0].load_balancer) == 1 &&
      one(aws_ecs_service.api[0].load_balancer).container_name == "api" &&
      one(aws_ecs_service.api[0].load_balancer).container_port == 8000 &&
      length(aws_ecs_service.detector[0].service_registries) == 1
    )
    error_message = "api behind the ALB on 8000; detector registered in Cloud Map."
  }
  assert {
    condition = (
      !can(jsondecode(aws_ecs_task_definition.detector[0].container_definitions)[0].secrets) &&
      jsondecode(aws_ecs_task_definition.detector[0].container_definitions)[0].healthCheck.startPeriod == 300 &&
      aws_ecs_task_definition.detector[0].task_role_arn == null
    )
    error_message = "Detector: no secrets, 300 s health start period, no task role."
  }
  assert {
    condition = (
      jsondecode(aws_ecs_task_definition.api[0].container_definitions)[0].command == ["python", "main.py"] &&
      length(jsondecode(aws_ecs_task_definition.api[0].container_definitions)[0].secrets) == 8 &&
      one([for e in jsondecode(aws_ecs_task_definition.api[0].container_definitions)[0].environment : e.value if e.name == "ENVIRONMENT"]) == "prod" &&
      one([for e in jsondecode(aws_ecs_task_definition.api[0].container_definitions)[0].environment : e.value if e.name == "FRONTEND_URL"]) == output.frontend_url
    )
    error_message = "api: python main.py (no migrate on boot), all 8 secrets, ENVIRONMENT=prod, FRONTEND_URL = the distribution."
  }
  assert {
    condition     = contains([for e in jsondecode(aws_ecs_task_definition.worker[0].container_definitions)[0].environment : e.name], "SQS_BATCHES_DLQ_URL")
    error_message = "Worker env has SQS_BATCHES_DLQ_URL."
  }
  assert {
    condition     = length(aws_scheduler_schedule.purge_sessions) == 1
    error_message = "Session purge schedule exists while running."
  }
}

# The free, stateful compute foundation must survive a pause.
run "paused" {
  command = apply
  variables { paused = true }

  assert {
    condition     = aws_ecs_cluster.main.name == "prompt-patrol" && aws_service_discovery_private_dns_namespace.main.name == "prompt-patrol.internal" && aws_cloudwatch_log_group.detector.retention_in_days == 14 && aws_iam_role.execution.name != "" && aws_security_group.detector.name == "prompt-patrol-detector"
    error_message = "Cluster, namespace, log groups, roles and SGs are free and never paused."
  }
  assert {
    condition     = length(aws_lb.api) == 0 && length(aws_lb_target_group.api) == 0 && length(aws_cloudfront_vpc_origin.alb) == 0 && length(aws_vpc_security_group_ingress_rule.alb_from_cloudfront) == 0
    error_message = "ALB, target group, VPC origin and the ALB ingress are hourly-billed or tied to them: paused."
  }
  assert {
    condition     = aws_s3_bucket.web.bucket == "prompt-patrol-web-420974348257" && aws_cloudfront_distribution.web.domain_name != "" && length(aws_cloudfront_distribution.web.ordered_cache_behavior) == 0 && length(aws_cloudfront_distribution.web.origin) == 1
    error_message = "Distribution and SPA bucket survive a pause (the domain is the app's identity); /api/* behavior and origin go."
  }
  assert {
    condition = (
      length(aws_ecs_service.api) + length(aws_ecs_service.worker) + length(aws_ecs_service.detector) == 0 &&
      length(aws_ecs_task_definition.api) + length(aws_ecs_task_definition.worker) + length(aws_ecs_task_definition.detector) == 0 &&
      length(aws_scheduler_schedule.purge_sessions) == 0
    )
    error_message = "Services, task definitions and the purge schedule are paused."
  }
}
