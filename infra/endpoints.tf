# Private paths to AWS services, so only the API task ever needs the NAT.

locals {
  # What every Fargate task needs at start (image pull, logs, injected
  # secrets) plus SQS for the API and Worker. S3 is the gateway endpoint below.
  interface_endpoints = ["ecr.api", "ecr.dkr", "logs", "secretsmanager", "sqs"]
}

# Free, so never paused. Also carries ECR image layers.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.ap-southeast-1.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.egress.id, aws_route_table.isolated.id]
  tags              = { Name = "prompt-patrol-s3" }
}

resource "aws_security_group" "endpoints" {
  name        = "prompt-patrol-vpc-endpoints"
  description = "HTTPS from inside the VPC to interface endpoints"
  vpc_id      = aws_vpc.main.id
}

# ponytail: whole VPC CIDR. Narrow to the workload SGs once they exist (step 5).
resource "aws_vpc_security_group_ingress_rule" "endpoints_https" {
  security_group_id = aws_security_group.endpoints.id
  cidr_ipv4         = aws_vpc.main.cidr_block
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

# One network interface per zone, so losing a zone doesn't cut the other off
# from ECR, Logs, Secrets Manager or SQS. Cost is controlled by `paused`, not
# by dropping a zone.
resource "aws_vpc_endpoint" "interface" {
  for_each            = var.paused ? toset([]) : toset(local.interface_endpoints)
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.ap-southeast-1.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.isolated[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
  tags                = { Name = "prompt-patrol-${each.key}" }
}
