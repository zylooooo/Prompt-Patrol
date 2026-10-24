# PP-533 load generator: an EC2 instance that runs k6 against the public URL,
# plus the EIP that the WAF allow rule (waf.tf) trusts and a private bucket to
# move the harness in and the results out. Off by default; on only while
# var.loadtest_enabled and not var.paused. Turn it off after each sitting.
# It reads (never writes) CloudWatch/SQS/ECS state. No session cookie or other
# secret ever goes into Terraform state, user_data or /etc/loadtest.env.

locals {
  loadtest = var.loadtest_enabled && !var.paused
}

data "aws_ssm_parameter" "loadtest_ami" {
  count = local.loadtest ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_instance" "loadtest" {
  count                       = local.loadtest ? 1 : 0
  ami                         = data.aws_ssm_parameter.loadtest_ami[0].value
  instance_type               = "t3.small"
  subnet_id                   = aws_subnet.public[0].id
  vpc_security_group_ids      = [aws_security_group.loadtest[0].id]
  iam_instance_profile        = aws_iam_instance_profile.loadtest[0].name
  associate_public_ip_address = false # the EIP below is its only public address
  monitoring                  = true  # 1-min EC2 CPU: the "load generator saturated" check

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  user_data = templatefile("${path.module}/loadtest-user-data.sh.tftpl", {
    base_url         = local.frontend_url
    cluster          = aws_ecs_cluster.main.name
    queue_url        = aws_sqs_queue.batches.url
    alb_suffix       = aws_lb.api[0].arn_suffix
    worker_log_group = aws_cloudwatch_log_group.worker.name
    bucket           = aws_s3_bucket.loadtest_transfer[0].bucket
  })
  user_data_replace_on_change = true

  lifecycle {
    ignore_changes = [ami] # a newer AL2023 AMI mid-sitting must not replace the instance
  }

  tags = { Name = "prompt-patrol-loadtest" }
}

resource "aws_eip" "loadtest" {
  count  = local.loadtest ? 1 : 0
  domain = "vpc"
  tags   = { Name = "prompt-patrol-loadtest" }
}

resource "aws_eip_association" "loadtest" {
  count         = local.loadtest ? 1 : 0
  instance_id   = aws_instance.loadtest[0].id
  allocation_id = aws_eip.loadtest[0].id
}

# --- Network -----------------------------------------------------------------

# No inbound (shell is Session Manager). 443 covers CloudFront, S3, Docker Hub
# and the SSM/AWS APIs.
resource "aws_security_group" "loadtest" {
  count       = local.loadtest ? 1 : 0
  name        = "prompt-patrol-loadtest"
  description = "PP-533 load generator"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_egress_rule" "loadtest_https" {
  count             = local.loadtest ? 1 : 0
  security_group_id = aws_security_group.loadtest[0].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

# --- IAM ---------------------------------------------------------------------

resource "aws_iam_role" "loadtest" {
  count = local.loadtest ? 1 : 0
  name  = "prompt-patrol-loadtest"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "loadtest_ssm" {
  count      = local.loadtest ? 1 : 0
  role       = aws_iam_role.loadtest[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "loadtest" {
  count = local.loadtest ? 1 : 0
  name  = "loadtest"
  role  = aws_iam_role.loadtest[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "cloudwatch:GetMetricData", Resource = "*" },
      { Effect = "Allow", Action = "logs:FilterLogEvents", Resource = "${aws_cloudwatch_log_group.worker.arn}:*" },
      { Effect = "Allow", Action = "sqs:GetQueueAttributes", Resource = aws_sqs_queue.batches.arn },
      {
        Effect   = "Allow"
        Action   = "ecs:DescribeServices"
        Resource = [aws_ecs_service.api[0].id, aws_ecs_service.worker[0].id, aws_ecs_service.detector[0].id]
      },
      { Effect = "Allow", Action = "ecs:DescribeTaskDefinition", Resource = "*" },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.loadtest_transfer[0].arn}/*"
      },
      { Effect = "Allow", Action = "s3:ListBucket", Resource = aws_s3_bucket.loadtest_transfer[0].arn },
    ]
  })
}

resource "aws_iam_instance_profile" "loadtest" {
  count = local.loadtest ? 1 : 0
  name  = "prompt-patrol-loadtest"
  role  = aws_iam_role.loadtest[0].name
}

# --- Transfer bucket ---------------------------------------------------------

# Harness tarball up, results back; avoids repo credentials on the instance.
resource "aws_s3_bucket" "loadtest_transfer" {
  count         = local.loadtest ? 1 : 0
  bucket        = "prompt-patrol-loadtest-420974348257"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "loadtest_transfer" {
  count                   = local.loadtest ? 1 : 0
  bucket                  = aws_s3_bucket.loadtest_transfer[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "loadtest_transfer" {
  count  = local.loadtest ? 1 : 0
  bucket = aws_s3_bucket.loadtest_transfer[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "loadtest_transfer" {
  count  = local.loadtest ? 1 : 0
  bucket = aws_s3_bucket.loadtest_transfer[0].id

  rule {
    id     = "expire"
    status = "Enabled"

    filter {}

    expiration {
      days = 30
    }
  }
}

# --- WAF ---------------------------------------------------------------------

# Lives in us-east-1 next to the CLOUDFRONT-scoped web ACL. The /32 is the EIP,
# known at apply time and stable across stop/start.
resource "aws_wafv2_ip_set" "loadtest" {
  provider           = aws.us_east_1
  count              = local.loadtest ? 1 : 0
  name               = "prompt-patrol-loadtest"
  scope              = "CLOUDFRONT"
  ip_address_version = "IPV4"
  addresses          = ["${aws_eip.loadtest[0].public_ip}/32"]
}
