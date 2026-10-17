# The state bucket is created by hand and deliberately not managed here (see README.md).
# No `profile`: locally set AWS_PROFILE=prompt-patrol; CI (step 7) supplies OIDC credentials via env.
provider "aws" {
  region              = "ap-southeast-1"
  allowed_account_ids = ["420974348257"]

  default_tags {
    tags = {
      Project   = "prompt-patrol"
      ManagedBy = "terraform"
    }
  }
}
