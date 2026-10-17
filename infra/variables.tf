variable "paused" {
  description = "Tear down everything billed by the hour (NAT, interface endpoints, later ALB/Fargate). Set it in terraform.tfvars, not with -var, so a CD apply can't silently undo it."
  type        = bool
  default     = false
}
