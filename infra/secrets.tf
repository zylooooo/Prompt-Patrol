# One secret per env var the API reads (apps/api/app/config/settings.py).
# Never gated on var.paused: a deleted name stays reserved for the recovery
# window. recovery_window_in_days = 0 so an end-of-project destroy can be
# re-created. AWS-managed key.
#
# Terraform writes only DB_URL (database.tf) and SESSION_SECRET (below), both
# write-only. The six AUTH0_* values are set by hand (console or
# `aws secretsmanager put-secret-value`); Terraform never reads or writes them.

locals {
  app_secrets = toset([
    "DB_URL",
    "SESSION_SECRET",
    "AUTH0_DOMAIN",
    "AUTH0_CLIENT_ID",
    "AUTH0_CLIENT_SECRET",
    "AUTH0_REDIRECT_URI",
    "AUTH0_M2M_CLIENT_ID",
    "AUTH0_M2M_CLIENT_SECRET",
  ])
}

resource "aws_secretsmanager_secret" "app" {
  for_each                = local.app_secrets
  name                    = "prompt-patrol/${each.key}"
  recovery_window_in_days = 0 # Change this to a higher value when production is stable, won't tear down again
}

ephemeral "random_password" "session_secret" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret_version" "session_secret" {
  secret_id                = aws_secretsmanager_secret.app["SESSION_SECRET"].id
  secret_string_wo         = ephemeral.random_password.session_secret.result
  secret_string_wo_version = 1 # bump to rotate
}
