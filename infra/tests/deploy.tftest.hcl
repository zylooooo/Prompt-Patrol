# Offline (mock provider). Guards the two things that must never loosen: who
# can assume the deploy role, and that image tags can't be overwritten.
mock_provider "aws" {
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
}
