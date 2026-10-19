# Offline (mock provider). Guards the two things that must never loosen: who
# can assume the deploy role, and that image tags can't be overwritten.
mock_provider "aws" {
  source = "./tests/mocks"
}

mock_provider "aws" {
  alias  = "us_east_1"
  source = "./tests/mocks"
}

run "deploy" {
  command = apply

  assert {
    condition = jsondecode(aws_iam_role.deploy.assume_role_policy).Statement[0].Condition == {
      StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = "repo:zylooooo/Prompt-Patrol:environment:production"
      }
    }
    error_message = "The deploy role must trust exactly the production environment of this repo, nothing looser."
  }

  assert {
    condition     = length(jsondecode(aws_iam_role.deploy.assume_role_policy).Statement) == 1
    error_message = "The deploy role must have a single trust statement."
  }

  assert {
    condition     = length(aws_ecr_repository.service) == 3 && alltrue([for r in aws_ecr_repository.service : r.image_tag_mutability == "IMMUTABLE" && r.image_scanning_configuration[0].scan_on_push])
    error_message = "All 3 ECR repos must have immutable tags and scan on push."
  }

  assert {
    condition     = length(aws_ecr_lifecycle_policy.service) == 3
    error_message = "Every ECR repo needs its lifecycle policy."
  }

  # deploy_role_can_tag_on_register
  assert {
    condition     = [for s in jsondecode(aws_iam_role_policy.deploy_release.policy).Statement : s if s.Sid == "TagOnRegister"][0].Condition == { StringEquals = { "ecs:CreateAction" = "RegisterTaskDefinition" } }
    error_message = "Registering tagged task definitions needs ecs:TagResource scoped to RegisterTaskDefinition."
  }

  assert {
    condition     = alltrue([for s in jsondecode(aws_iam_role_policy.deploy_release.policy).Statement : s.Resource != "*" || s.Sid == "TaskDefinitionsUnscopable"])
    error_message = "Only the unscopable task-definition actions may use Resource *."
  }

  assert {
    condition = (
      flatten([[for s in jsondecode(aws_iam_role_policy.deploy_release.policy).Statement : s if s.Sid == "RecordLiveSha"][0].Action]) == ["ssm:PutParameter"]
      && [for s in jsondecode(aws_iam_role_policy.deploy_release.policy).Statement : s if s.Sid == "RecordLiveSha"][0].Resource == aws_ssm_parameter.image_tag.arn
    )
    error_message = "The pipeline may write only the live-SHA parameter."
  }

  assert {
    condition = (
      [for s in jsondecode(aws_iam_role_policy.deploy_release.policy).Statement : s if s.Sid == "PassTaskRoles"][0].Condition == { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } }
      && length([for s in jsondecode(aws_iam_role_policy.deploy_release.policy).Statement : s if s.Sid == "PassTaskRoles"][0].Resource) == 3
    )
    error_message = "PassRole only for the 3 task roles, only to ECS tasks."
  }

  assert {
    condition     = alltrue([for s in jsondecode(aws_iam_role_policy.deploy_release.policy).Statement : !contains(flatten([s.Action]), "*")])
    error_message = "No wildcard actions."
  }
}
