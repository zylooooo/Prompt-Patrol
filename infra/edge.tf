# Edge: CloudFront in front of the SPA bucket and, via a VPC origin, the
# internal ALB. The ALB and VPC origin are hourly-billed, so they follow
# var.paused. The distribution and SPA bucket never do: app_hostname, its
# alias, is the app's identity (FRONTEND_URL, AUTH0_REDIRECT_URI, Auth0
# allowed URLs; change them together).

locals {
  app_hostname = "app.prompt-patrol.com"
  frontend_url = "https://${local.app_hostname}"
}

# --- Custom domain -----------------------------------------------------------

# Registered by hand in Route 53 (Registrar created the zone), so read, not managed.
data "aws_route53_zone" "main" {
  name = "prompt-patrol.com"
}

# CloudFront only accepts ACM certificates from us-east-1.
resource "aws_acm_certificate" "web" {
  provider          = aws.us_east_1
  domain_name       = local.app_hostname
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# One host, so exactly one validation record (no SANs to loop over).
resource "aws_route53_record" "cert_validation" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = one(aws_acm_certificate.web.domain_validation_options).resource_record_name
  type    = one(aws_acm_certificate.web.domain_validation_options).resource_record_type
  records = [one(aws_acm_certificate.web.domain_validation_options).resource_record_value]
  ttl     = 300
}

resource "aws_acm_certificate_validation" "web" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.web.arn
  validation_record_fqdns = [aws_route53_record.cert_validation.fqdn]
}

# A only: the distribution is IPv4-only (is_ipv6_enabled = false).
resource "aws_route53_record" "app" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = local.app_hostname
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.web.domain_name
    zone_id                = aws_cloudfront_distribution.web.hosted_zone_id
    evaluate_target_health = false
  }
}

# --- Internal ALB ------------------------------------------------------------

# Isolated subnets: it only talks to the VPC origin and the API tasks. No TLS on
# this hop: no domain of ours to certify, and it stays inside AWS's network.
resource "aws_lb" "api" {
  count                      = var.paused ? 0 : 1
  name                       = "prompt-patrol"
  internal                   = true
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.isolated[*].id
  idle_timeout               = 60
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "api" {
  count                = var.paused ? 0 : 1
  name                 = "prompt-patrol-api"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30

  health_check {
    path    = "/health"
    matcher = "200"
  }
}

resource "aws_lb_listener" "http" {
  count             = var.paused ? 0 : 1
  load_balancer_arn = aws_lb.api[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[0].arn
  }
}

# Create/delete takes several minutes; accepted for the pause savings.
resource "aws_cloudfront_vpc_origin" "alb" {
  count = var.paused ? 0 : 1

  vpc_origin_endpoint_config {
    name                   = "prompt-patrol-alb"
    arn                    = aws_lb.api[0].arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "http-only"

    # Required by the API even for http-only; unused.
    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }

  # On pause the distribution drops this origin in the same apply. Without
  # this, Terraform deletes the origin first and CloudFront refuses (409, still
  # in use); with it, the distribution update runs first. Terraform also treats
  # the ALB as create-before-destroy, so a forced replacement of either would
  # hit a name clash: pause and resume instead.
  lifecycle {
    create_before_destroy = true
  }
}

# AWS creates this SG with the VPC origin (it may appear only once a
# distribution uses it). Allowing it, not CloudFront's prefix list, admits our
# distributions only.
data "aws_security_group" "cloudfront_vpc_origin" {
  count = var.paused ? 0 : 1

  filter {
    name   = "group-name"
    values = ["CloudFront-VPCOrigins-Service-SG"]
  }
  filter {
    name   = "vpc-id"
    values = [aws_vpc.main.id]
  }

  depends_on = [aws_cloudfront_vpc_origin.alb, aws_cloudfront_distribution.web]
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_cloudfront" {
  count                        = var.paused ? 0 : 1
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = data.aws_security_group.cloudfront_vpc_origin[0].id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
}

# --- SPA bucket --------------------------------------------------------------

resource "aws_s3_bucket" "web" {
  bucket        = "prompt-patrol-web-420974348257"
  force_destroy = true # so the end-of-project destroy works with objects inside
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# SSE-S3, not KMS: OAC reading SSE-KMS objects needs a key policy too.
resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        # SourceArn: only this distribution, not any CloudFront in any account.
        Sid       = "CloudFrontOacRead"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.web.arn}/*"
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } }
      },
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.web]
}

# --- CloudFront --------------------------------------------------------------

data "aws_cloudfront_cache_policy" "caching_optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

# Cookies, query strings, Origin and Sec-Fetch-Site reach the API (CSRF check).
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "prompt-patrol-web"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Client-side routes (no file extension) get index.html. Done here rather than
# custom_error_response, which would also rewrite the API's deliberate 404s.
resource "aws_cloudfront_function" "spa_rewrite" {
  name    = "prompt-patrol-spa-rewrite"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      if (request.uri.split('/').pop().indexOf('.') === -1) {
        request.uri = '/index.html';
      }
      return request;
    }
  EOT
}

# Security headers on every response (SPA and /api/*). Values mirror
# apps/web/nginx.conf (change both together). connect-src lists both S3 hosts
# of the batches bucket: the pinned boto3 signs the global host and an upgrade
# may switch to the regional one, and a CSP miss is silent (the upload just
# fails in the browser). HSTS is 1 year with no includeSubDomains/preload
# because this hostname is fixed and not ours to commit a whole domain on.
# override = true so these win over anything the origin sends.
resource "aws_cloudfront_response_headers_policy" "security" {
  name = "prompt-patrol-security"

  security_headers_config {
    content_security_policy {
      content_security_policy = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://${aws_s3_bucket.batches.bucket_domain_name} https://${aws_s3_bucket.batches.bucket_regional_domain_name}; form-action 'self' https://*.auth0.com; frame-ancestors 'none'; frame-src 'none'; object-src 'none'; base-uri 'self'"
      override                = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = false
      preload                    = false
      override                   = true
    }
  }

  # No typed block for Permissions-Policy.
  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
      override = true
    }
  }
}

# PriceClass_200 includes the Singapore edges; 100 does not. IPv4 only: a
# dual-stack VPC origin needs more setup.
resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  comment             = "prompt-patrol"
  price_class         = "PriceClass_200"
  http_version        = "http2and3"
  is_ipv6_enabled     = false
  default_root_object = "index.html"
  web_acl_id          = var.paused ? null : aws_wafv2_web_acl.main[0].arn

  origin {
    origin_id                = "web"
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  # While paused, /api/* falls through to the SPA.
  dynamic "origin" {
    for_each = aws_cloudfront_vpc_origin.alb
    content {
      origin_id   = "api"
      domain_name = aws_lb.api[0].dns_name

      vpc_origin_config {
        vpc_origin_id       = origin.value.id
        origin_read_timeout = 60 # a single check can wait up to 30 s on the detector
      }
    }
  }

  default_cache_behavior {
    target_origin_id           = "web"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    compress                   = true

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_rewrite.arn
    }
  }

  dynamic "ordered_cache_behavior" {
    for_each = aws_cloudfront_vpc_origin.alb
    content {
      path_pattern               = "/api/*"
      target_origin_id           = "api"
      viewer_protocol_policy     = "redirect-to-https"
      allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods             = ["GET", "HEAD"]
      cache_policy_id            = data.aws_cloudfront_cache_policy.caching_disabled.id
      origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
      response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    }
  }

  # No custom_error_response: it is distribution-wide (see spa_rewrite).

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  aliases = [local.app_hostname]

  # sni-only: "vip" is a dedicated IP at $600/month.
  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.web.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}
