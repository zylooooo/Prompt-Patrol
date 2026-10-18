variable "paused" {
  description = "Tear down everything billed by the hour (NAT, interface endpoints, later ALB/Fargate). Set it in terraform.tfvars, not with -var, so a CD apply can't silently undo it."
  type        = bool
  default     = false

  # Otherwise the pause deletes the DB_URL version, then the protected DB
  # refuses deletion, and the next unpause writes a password the DB never got.
  validation {
    condition     = !(var.paused && var.db_deletion_protection)
    error_message = "Can't pause while db_deletion_protection = true. Take two applies: (1) db_deletion_protection = false with paused = false, apply; (2) then paused = true, apply. If done in one apply, bump db_password_version."
  }
}

variable "db_deletion_protection" {
  description = "Set true in terraform.tfvars for the final demo & production build: a pause or destroy then fails instead of deleting the database."
  type        = bool
  default     = false
}

variable "image_tag" {
  description = "Commit SHA of the images in ECR; all three services use it. Step 7's CD replaces this."
  type        = string
}
