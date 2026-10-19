# GitHub Actions signs in to AWS with short-lived OIDC tokens; no AWS keys are
# stored in GitHub. Only jobs running in the `production` environment, which
# requires a reviewer to approve, can assume the deploy role.

locals {
  github_repo = "zylooooo/Prompt-Patrol"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "deploy" {
  name        = "prompt-patrol-deploy"
  description = "GitHub Actions deploy job, environment production only"

  # Exact match, no wildcard: the repo is public, so anything looser would let
  # other branches or workflows assume it. Which branches may use the
  # environment is GitHub's deployment-branch rule.
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:${local.github_repo}:environment:production"
        }
      }
    }]
  })
}

# Step 3: copy images into ECR. The `release` policy below (step 7) adds the
# rollout permissions.
resource "aws_iam_role_policy" "deploy_ecr_push" {
  name = "ecr-push"
  role = aws_iam_role.deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrLogin" # account-wide by AWS design
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "PushToServiceRepos"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:CompleteLayerUpload",
          "ecr:DescribeImages",
          "ecr:GetDownloadUrlForLayer",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
        ]
        Resource = [for r in aws_ecr_repository.service : r.arn]
      },
    ]
  })
}

# Roll out a release (ECS task definitions + services, migration task,
# SPA sync, CloudFront invalidation, live-SHA parameter).
resource "aws_iam_role_policy" "deploy_release" {
  name = "release"
  role = aws_iam_role.deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TaskDefinitionsUnscopable" # AWS cannot scope these to a resource
        Effect = "Allow"
        Action = [
          "ecs:RegisterTaskDefinition",
          "ecs:DescribeTaskDefinition",
          "ecs:DeregisterTaskDefinition",
        ]
        Resource = "*"
      },
      {
        # --tags on register needs TagResource, only valid during that call.
        Sid       = "TagOnRegister"
        Effect    = "Allow"
        Action    = "ecs:TagResource"
        Resource  = "arn:aws:ecs:ap-southeast-1:420974348257:task-definition/prompt-patrol-*"
        Condition = { StringEquals = { "ecs:CreateAction" = "RegisterTaskDefinition" } }
      },
      {
        Sid      = "Services"
        Effect   = "Allow"
        Action   = ["ecs:DescribeServices", "ecs:UpdateService"]
        Resource = "arn:aws:ecs:ap-southeast-1:420974348257:service/prompt-patrol/*"
      },
      {
        Sid       = "MigrationTask"
        Effect    = "Allow"
        Action    = "ecs:RunTask"
        Resource  = "arn:aws:ecs:ap-southeast-1:420974348257:task-definition/prompt-patrol-api:*"
        Condition = { ArnEquals = { "ecs:cluster" = aws_ecs_cluster.main.arn } }
      },
      {
        Sid      = "MigrationTaskStatus"
        Effect   = "Allow"
        Action   = "ecs:DescribeTasks"
        Resource = "arn:aws:ecs:ap-southeast-1:420974348257:task/prompt-patrol/*"
      },
      {
        Sid    = "PassTaskRoles"
        Effect = "Allow"
        Action = "iam:PassRole"
        Resource = [
          aws_iam_role.execution.arn,
          aws_iam_role.api_task.arn,
          aws_iam_role.worker_task.arn,
        ]
        Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } }
      },
      {
        Sid      = "MigrationLogs"
        Effect   = "Allow"
        Action   = "logs:GetLogEvents"
        Resource = "${aws_cloudwatch_log_group.api.arn}:log-stream:*"
      },
      {
        Sid    = "ReleaseParams"
        Effect = "Allow"
        Action = "ssm:GetParameter"
        Resource = [
          aws_ssm_parameter.image_tag.arn,
          aws_ssm_parameter.cloudfront_distribution_id.arn,
        ]
      },
      {
        Sid      = "RecordLiveSha"
        Effect   = "Allow"
        Action   = "ssm:PutParameter"
        Resource = aws_ssm_parameter.image_tag.arn
      },
      {
        Sid      = "WebBucketList"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.web.arn
      },
      {
        Sid      = "WebBucketObjects"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.web.arn}/*"
      },
      {
        Sid      = "Invalidate"
        Effect   = "Allow"
        Action   = "cloudfront:CreateInvalidation"
        Resource = "arn:aws:cloudfront::420974348257:distribution/${aws_cloudfront_distribution.web.id}"
      },
    ]
  })
}
