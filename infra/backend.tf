# The bucket is hand-made and deliberately outside Terraform (see README.md).
# Backend blocks can't use variables, so every value here is a literal.
terraform {
  backend "s3" {
    bucket       = "prompt-patrol-tfstate-420974348257"
    key          = "app/terraform.tfstate"
    region       = "ap-southeast-1"
    encrypt      = true
    use_lockfile = true
  }
}
