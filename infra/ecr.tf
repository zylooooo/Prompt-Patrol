# What AWS runs from. CI keeps every build in GHCR; the approved deploy job
# copies a commit's images here by digest (see README.md "Images and deploys").
# Storage, not hourly, so not gated on var.paused.

locals {
  ecr_repositories = ["api", "worker", "detector"]
}

resource "aws_ecr_repository" "service" {
  for_each             = toset(local.ecr_repositories)
  name                 = "prompt-patrol/${each.key}"
  image_tag_mutability = "IMMUTABLE" # tags are commit SHAs; a tag never moves
  force_delete         = true        # so the end-of-project destroy works with images inside

  image_scanning_configuration {
    scan_on_push = true # basic scanning, free
  }
}

resource "aws_ecr_lifecycle_policy" "service" {
  for_each   = aws_ecr_repository.service
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Drop untagged images after a day"
        selection    = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 1 }
        action       = { type = "expire" }
      },
      # Counts tagged images only. Buildx pushes each build as a tagged index
      # plus two untagged children (image, provenance); "any" would count all
      # three and keep ~3 deploys. Children of a kept index can't be expired.
      {
        rulePriority = 2
        description  = "Keep the newest 10 deploys (the detector image is several GB)"
        selection    = { tagStatus = "tagged", tagPatternList = ["*"], countType = "imageCountMoreThan", countNumber = 10 }
        action       = { type = "expire" }
      },
    ]
  })
}
