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

variable "loadtest_enabled" {
  description = "PP-533 load-test window: EC2 load generator + WAF allow rule for its EIP. Pre-go-live only; turn off after each sitting."
  type        = bool
  default     = false
}

variable "detector_torch_threads" {
  description = "Torch intra-op threads for the detector (DETECTOR_TORCH_THREADS). PP-533: a second thread on 2 vCPU added nothing (Phase 7). null = the code's default, one per CPU the task sees."
  type        = number
  default     = 1

  validation {
    condition     = var.detector_torch_threads == null || try(var.detector_torch_threads >= 1, false)
    error_message = "detector_torch_threads must be at least 1, or null for the default."
  }
}
