# WAF in front of the distribution. CloudFront-scoped web ACLs exist only in
# us-east-1, hence the aliased provider. Hourly-billed, so it follows
# var.paused; the distribution drops its web_acl_id in the same apply.
#
# It never blocks on request bodies: the managed groups' *_BODY rules are forced
# to Count. Check bodies carry student answers that often contain code
# (<script>, SQL, ${jndi:...}) and run up to 10,000 + 2,000 characters, past the
# Core Rule Set's 8 KB SizeRestrictions_BODY limit, so a body rule would 403 a
# legitimate check. Header/URI/query rules still block.
#
# Sampled requests are off everywhere: they store full request headers in the
# WAF console, which would include the __Host- session cookie. Metrics stay on.
# There is deliberately no logging configuration for the same reason.
#
# create_before_destroy: a web ACL cannot be deleted while a distribution still
# references it, so a replacement must exist first.

locals {
  # From `aws wafv2 describe-managed-rule-group` (us-east-1, CLOUDFRONT), 2026-10-19:
  # every rule whose name ends _BODY. Re-run when AWS adds rules; a new _BODY
  # rule not listed here would block (tests only compare against this list).
  crs_body_rules = [
    "SizeRestrictions_BODY",
    "EC2MetaDataSSRF_BODY",
    "GenericLFI_BODY",
    "GenericRFI_BODY",
    "CrossSiteScripting_BODY",
  ]
  kbi_body_rules = [
    "JavaDeserializationRCE_BODY",
    "Log4JRCE_BODY",
    "ReactJSRCE_BODY",
  ]
}

resource "aws_wafv2_web_acl" "main" {
  provider    = aws.us_east_1
  count       = var.paused ? 0 : 1
  name        = "prompt-patrol"
  scope       = "CLOUDFRONT"
  description = "prompt-patrol edge protection"

  default_action {
    allow {}
  }

  rule {
    name     = "ip-reputation"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      sampled_requests_enabled   = false
      metric_name                = "prompt-patrol-ip-reputation"
    }
  }

  rule {
    name     = "rate-all"
    priority = 2

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit                 = 2000
        evaluation_window_sec = 300
        aggregate_key_type    = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      sampled_requests_enabled   = false
      metric_name                = "prompt-patrol-rate-all"
    }
  }

  # Tighter limit on state-changing API calls only.
  rule {
    name     = "rate-writes"
    priority = 3

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit                 = 300
        evaluation_window_sec = 300
        aggregate_key_type    = "IP"

        scope_down_statement {
          and_statement {
            statement {
              or_statement {
                dynamic "statement" {
                  for_each = ["POST", "PUT", "PATCH", "DELETE"]
                  content {
                    byte_match_statement {
                      search_string         = statement.value
                      positional_constraint = "EXACTLY"
                      field_to_match {
                        method {}
                      }
                      text_transformation {
                        priority = 0
                        type     = "NONE"
                      }
                    }
                  }
                }
              }
            }
            statement {
              byte_match_statement {
                search_string         = "/api/"
                positional_constraint = "STARTS_WITH"
                field_to_match {
                  uri_path {}
                }
                text_transformation {
                  priority = 0
                  type     = "NONE"
                }
              }
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      sampled_requests_enabled   = false
      metric_name                = "prompt-patrol-rate-writes"
    }
  }

  rule {
    name     = "common-rule-set"
    priority = 4

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"

        dynamic "rule_action_override" {
          for_each = local.crs_body_rules
          content {
            name = rule_action_override.value
            action_to_use {
              count {}
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      sampled_requests_enabled   = false
      metric_name                = "prompt-patrol-common-rule-set"
    }
  }

  rule {
    name     = "known-bad-inputs"
    priority = 5

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"

        dynamic "rule_action_override" {
          for_each = local.kbi_body_rules
          content {
            name = rule_action_override.value
            action_to_use {
              count {}
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      sampled_requests_enabled   = false
      metric_name                = "prompt-patrol-known-bad-inputs"
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    sampled_requests_enabled   = false
    metric_name                = "prompt-patrol"
  }

  lifecycle {
    create_before_destroy = true
  }
}
