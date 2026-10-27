# Offline (mock provider). Step 6 edge protection: the WAF web ACL's rule
# order, limits and body-rule Count overrides, and that it is paused with the rest.
mock_provider "aws" {
  source = "./tests/mocks"
}

mock_provider "aws" {
  alias  = "us_east_1"
  source = "./tests/mocks"
}

run "running" {
  command = apply
  variables { paused = false }

  assert {
    condition = (
      length(aws_wafv2_web_acl.main) == 1 &&
      aws_wafv2_web_acl.main[0].name == "prompt-patrol" &&
      aws_wafv2_web_acl.main[0].scope == "CLOUDFRONT" &&
      length(aws_wafv2_web_acl.main[0].default_action[0].allow) == 1 &&
      aws_cloudfront_distribution.web.web_acl_id == aws_wafv2_web_acl.main[0].arn
    )
    error_message = "One CLOUDFRONT web ACL, default allow, attached to the distribution."
  }

  assert {
    condition = (
      one([for r in aws_wafv2_web_acl.main[0].rule : r.priority if r.name == "ip-reputation"]) == 1 &&
      one([for r in aws_wafv2_web_acl.main[0].rule : r.priority if r.name == "rate-all"]) == 2 &&
      one([for r in aws_wafv2_web_acl.main[0].rule : r.priority if r.name == "rate-writes"]) == 3 &&
      one([for r in aws_wafv2_web_acl.main[0].rule : r.priority if r.name == "common-rule-set"]) == 4 &&
      one([for r in aws_wafv2_web_acl.main[0].rule : r.priority if r.name == "known-bad-inputs"]) == 5 &&
      length(aws_wafv2_web_acl.main[0].rule) == 5
    )
    error_message = "Rule priorities: ip-reputation 1, rate-all 2, rate-writes 3, common-rule-set 4, known-bad-inputs 5."
  }

  assert {
    condition = (
      one([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].rate_based_statement[0].limit if r.name == "rate-all"]) == 2000 &&
      one([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].rate_based_statement[0].evaluation_window_sec if r.name == "rate-all"]) == 300 &&
      one([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].rate_based_statement[0].aggregate_key_type if r.name == "rate-all"]) == "IP" &&
      one([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].rate_based_statement[0].limit if r.name == "rate-writes"]) == 300 &&
      one([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].rate_based_statement[0].evaluation_window_sec if r.name == "rate-writes"]) == 300 &&
      one([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].rate_based_statement[0].aggregate_key_type if r.name == "rate-writes"]) == "IP"
    )
    error_message = "rate-all 2000 and rate-writes 300 per 300 s, keyed on IP."
  }

  # scope-down = (method in the OR) AND (path starts with /api/)
  assert {
    condition = (
      length(one([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].rate_based_statement[0].scope_down_statement[0].and_statement[0].statement if r.name == "rate-writes"])) == 2 &&
      toset(flatten([for s in one([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].rate_based_statement[0].scope_down_statement[0].and_statement[0].statement if r.name == "rate-writes"]) : [for m in flatten([for o in s.or_statement : o.statement]) : m.byte_match_statement[0].search_string if length(m.byte_match_statement[0].field_to_match[0].method) == 1 && m.byte_match_statement[0].positional_constraint == "EXACTLY"]])) == toset(["POST", "PUT", "PATCH", "DELETE"]) &&
      length(flatten([for s in one([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].rate_based_statement[0].scope_down_statement[0].and_statement[0].statement if r.name == "rate-writes"]) : flatten([for o in s.or_statement : o.statement])])) == 4
    )
    error_message = "rate-writes counts only POST/PUT/PATCH/DELETE ..."
  }
  assert {
    condition = (
      one(flatten([for s in one([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].rate_based_statement[0].scope_down_statement[0].and_statement[0].statement if r.name == "rate-writes"]) : [for m in s.byte_match_statement : m.search_string if length(m.field_to_match[0].uri_path) == 1 && m.positional_constraint == "STARTS_WITH"]])) == "/api/"
    )
    error_message = "... AND a URI path that STARTS_WITH /api/."
  }
  assert {
    condition     = toset([for o in one([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].managed_rule_group_statement[0] if r.name == "common-rule-set"]).rule_action_override : o.name if length(o.action_to_use[0].count) == 1]) == toset(local.crs_body_rules)
    error_message = "Common Rule Set: exactly the *_BODY rules are overridden to Count."
  }
  assert {
    condition     = toset([for o in one([for r in aws_wafv2_web_acl.main[0].rule : r.statement[0].managed_rule_group_statement[0] if r.name == "known-bad-inputs"]).rule_action_override : o.name if length(o.action_to_use[0].count) == 1]) == toset(local.kbi_body_rules)
    error_message = "Known Bad Inputs: exactly the *_BODY rules are overridden to Count."
  }

  assert {
    condition = (
      length(one([for r in aws_wafv2_web_acl.main[0].rule : r.action[0].block if r.name == "rate-all"])) == 1 &&
      length(one([for r in aws_wafv2_web_acl.main[0].rule : r.action[0].block if r.name == "rate-writes"])) == 1 &&
      length(one([for r in aws_wafv2_web_acl.main[0].rule : r.override_action[0].none if r.name == "common-rule-set"])) == 1 &&
      length(one([for r in aws_wafv2_web_acl.main[0].rule : r.override_action[0].none if r.name == "known-bad-inputs"])) == 1
    )
    error_message = "Rate rules block; managed groups use override_action none."
  }

  # Sampled requests would store the session cookie header in WAF's console.
  assert {
    condition = (
      aws_wafv2_web_acl.main[0].visibility_config[0].sampled_requests_enabled == false &&
      alltrue([for r in aws_wafv2_web_acl.main[0].rule : r.visibility_config[0].sampled_requests_enabled == false])
    )
    error_message = "Sampled requests off on the ACL and every rule (session cookie exposure)."
  }

  assert {
    condition     = aws_cloudfront_distribution.web.ordered_cache_behavior[0].response_headers_policy_id == aws_cloudfront_response_headers_policy.security.id
    error_message = "Security headers policy on /api/*."
  }

  assert {
    condition = (
      aws_cloudfront_distribution.web.default_cache_behavior[0].response_headers_policy_id == aws_cloudfront_response_headers_policy.security.id
    )
    error_message = "Security headers policy on the default behavior."
  }

  assert {
    condition = (
      strcontains(aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].content_security_policy, "connect-src 'self' https://${aws_s3_bucket.batches.bucket_domain_name} https://${aws_s3_bucket.batches.bucket_regional_domain_name};") &&
      strcontains(aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].content_security_policy, "frame-ancestors 'none'") &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].override == true
    )
    error_message = "CSP connect-src lists both batches S3 hosts; frame-ancestors none; override on."
  }

  assert {
    condition = (
      aws_cloudfront_response_headers_policy.security.name == "prompt-patrol-security" &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].strict_transport_security[0].access_control_max_age_sec == 31536000 &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].strict_transport_security[0].include_subdomains == false &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].strict_transport_security[0].preload == false &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].strict_transport_security[0].override == true &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].frame_options[0].frame_option == "DENY" &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].frame_options[0].override == true &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_type_options[0].override == true &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].referrer_policy[0].referrer_policy == "strict-origin-when-cross-origin" &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].referrer_policy[0].override == true &&
      one(aws_cloudfront_response_headers_policy.security.custom_headers_config[0].items).header == "Permissions-Policy" &&
      one(aws_cloudfront_response_headers_policy.security.custom_headers_config[0].items).value == "camera=(), microphone=(), geolocation=(), interest-cohort=()" &&
      one(aws_cloudfront_response_headers_policy.security.custom_headers_config[0].items).override == true
    )
    error_message = "HSTS 1y (no subdomains/preload), DENY, nosniff, referrer policy, Permissions-Policy, all override."
  }

  assert {
    condition = (
      length(aws_s3_bucket_cors_configuration.batches.cors_rule) == 1 &&
      one(aws_s3_bucket_cors_configuration.batches.cors_rule).allowed_origins == toset([local.frontend_url]) &&
      one(aws_s3_bucket_cors_configuration.batches.cors_rule).allowed_methods == toset(["PUT"]) &&
      one(aws_s3_bucket_cors_configuration.batches.cors_rule).allowed_headers == toset(["content-type"]) &&
      one(aws_s3_bucket_cors_configuration.batches.cors_rule).max_age_seconds == 3000 &&
      length(coalesce(one(aws_s3_bucket_cors_configuration.batches.cors_rule).expose_headers, [])) == 0
    )
    error_message = "Batches CORS: PUT from the frontend origin only, content-type header, no expose_headers."
  }
}

run "paused" {
  command = apply
  variables { paused = true }

  assert {
    condition     = length(aws_wafv2_web_acl.main) == 0 && aws_cloudfront_distribution.web.web_acl_id == null
    error_message = "Web ACL is hourly-billed: paused, and detached from the distribution."
  }

  assert {
    condition = (
      aws_cloudfront_distribution.web.default_cache_behavior[0].response_headers_policy_id == aws_cloudfront_response_headers_policy.security.id
    )
    error_message = "Security headers policy on the default behavior."
  }

  assert {
    condition = (
      strcontains(aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].content_security_policy, "connect-src 'self' https://${aws_s3_bucket.batches.bucket_domain_name} https://${aws_s3_bucket.batches.bucket_regional_domain_name};") &&
      strcontains(aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].content_security_policy, "frame-ancestors 'none'") &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_security_policy[0].override == true
    )
    error_message = "CSP connect-src lists both batches S3 hosts; frame-ancestors none; override on."
  }

  assert {
    condition = (
      aws_cloudfront_response_headers_policy.security.name == "prompt-patrol-security" &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].strict_transport_security[0].access_control_max_age_sec == 31536000 &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].strict_transport_security[0].include_subdomains == false &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].strict_transport_security[0].preload == false &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].strict_transport_security[0].override == true &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].frame_options[0].frame_option == "DENY" &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].frame_options[0].override == true &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].content_type_options[0].override == true &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].referrer_policy[0].referrer_policy == "strict-origin-when-cross-origin" &&
      aws_cloudfront_response_headers_policy.security.security_headers_config[0].referrer_policy[0].override == true &&
      one(aws_cloudfront_response_headers_policy.security.custom_headers_config[0].items).header == "Permissions-Policy" &&
      one(aws_cloudfront_response_headers_policy.security.custom_headers_config[0].items).value == "camera=(), microphone=(), geolocation=(), interest-cohort=()" &&
      one(aws_cloudfront_response_headers_policy.security.custom_headers_config[0].items).override == true
    )
    error_message = "HSTS 1y (no subdomains/preload), DENY, nosniff, referrer policy, Permissions-Policy, all override."
  }

  assert {
    condition = (
      length(aws_s3_bucket_cors_configuration.batches.cors_rule) == 1 &&
      one(aws_s3_bucket_cors_configuration.batches.cors_rule).allowed_origins == toset([local.frontend_url]) &&
      one(aws_s3_bucket_cors_configuration.batches.cors_rule).allowed_methods == toset(["PUT"]) &&
      one(aws_s3_bucket_cors_configuration.batches.cors_rule).allowed_headers == toset(["content-type"]) &&
      one(aws_s3_bucket_cors_configuration.batches.cors_rule).max_age_seconds == 3000 &&
      length(coalesce(one(aws_s3_bucket_cors_configuration.batches.cors_rule).expose_headers, [])) == 0
    )
    error_message = "Batches CORS: PUT from the frontend origin only, content-type header, no expose_headers."
  }
}
