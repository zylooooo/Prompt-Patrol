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

# Step 3: copy images into ECR. Step 7 adds the ECS deploy permissions.
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
