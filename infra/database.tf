# Postgres for the API, worker and migration task. Disposable: it follows
# var.paused like the NAT, and a pause deletes it with no final snapshot.
# Demo data is seeded fresh; set db_deletion_protection for the demo build.

resource "aws_db_subnet_group" "main" {
  name       = "prompt-patrol"
  subnet_ids = aws_subnet.database[*].id
}

# No rules here: step 5 adds 5432 ingress from the API, worker and migration
# task SGs.
resource "aws_security_group" "database" {
  name        = "prompt-patrol-database"
  description = "Postgres; ingress only from the app task SGs"
  vpc_id      = aws_vpc.main.id
}

# Never in state or plan: one ephemeral value feeds both the DB and DB_URL in
# the same apply (hashicorp/random: generated locally, so the mocked tests
# can run it). No punctuation keeps it URL-safe and clear of RDS's
# forbidden / @ " and space.
# One version for both sides: bumping it sends the same new password to the DB
# and DB_URL in one apply. Bump it if they ever disagree (e.g. an apply that
# created the DB but failed before writing DB_URL).
locals {
  db_password_version = 1
}

ephemeral "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_db_instance" "main" {
  count = var.paused ? 0 : 1

  identifier                 = "prompt-patrol"
  engine                     = "postgres"
  engine_version             = "18"
  auto_minor_version_upgrade = true
  instance_class             = "db.t4g.micro"
  multi_az                   = false
  storage_type               = "gp3"
  allocated_storage          = 20
  max_allocated_storage      = 100
  storage_encrypted          = true

  db_name             = "promptpatrol"
  username            = "promptpatrol"
  password_wo         = ephemeral.random_password.db.result
  password_wo_version = local.db_password_version

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false

  backup_retention_period = 1
  skip_final_snapshot     = true
  deletion_protection     = var.db_deletion_protection
}

# Follows the DB: a pause removes the version from state (the stale value stays
# AWSCURRENT in AWS until the next unpause writes a new one with the new DB). replace_triggered_by covers a DB replacement or new
# endpoint without a pause.
# ssl=verify-full: the cert must chain to PGSSLROOTCERT (compute.tf) and match
# the endpoint. The value is write-only, so editing this string alone never
# reaches AWS: the live secret was moved from ssl=require by hand
# (put-secret-value) on 2026-10-20 to avoid a password rotation. The next
# version bump or unpause writes this string.
resource "aws_secretsmanager_secret_version" "db_url" {
  count = var.paused ? 0 : 1

  secret_id                = aws_secretsmanager_secret.app["DB_URL"].id
  secret_string_wo         = "postgresql+asyncpg://promptpatrol:${ephemeral.random_password.db.result}@${aws_db_instance.main[count.index].address}:5432/promptpatrol?ssl=verify-full"
  secret_string_wo_version = local.db_password_version

  lifecycle {
    replace_triggered_by = [
      aws_db_instance.main[count.index].id,
      aws_db_instance.main[count.index].address,
    ]
  }
}
