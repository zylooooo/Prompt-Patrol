# Offline (mock provider). The PP-533 load-test toggle must stay closed by
# default: no instance, no IP set, no WAF allow rule.
mock_provider "aws" {
  source = "./tests/mocks"
}

mock_provider "aws" {
  alias  = "us_east_1"
  source = "./tests/mocks"
}

run "off_by_default" {
  command = apply
  variables { paused = false }

  assert {
    condition     = length(aws_instance.loadtest) == 0 && length(aws_wafv2_ip_set.loadtest) == 0
    error_message = "Load generator and its IP set must not exist by default."
  }
  assert {
    condition     = length(aws_wafv2_web_acl.main[0].rule) == 5 && !contains([for r in aws_wafv2_web_acl.main[0].rule : r.name], "loadtest-allow")
    error_message = "No loadtest-allow rule while the toggle is off."
  }
}

run "on" {
  command = apply
  variables {
    paused           = false
    loadtest_enabled = true
  }

  assert {
    condition = (
      length([for r in aws_wafv2_web_acl.main[0].rule : r if r.name == "loadtest-allow"]) == 1 &&
      one([for r in aws_wafv2_web_acl.main[0].rule : r if r.name == "loadtest-allow"]).priority == 0 &&
      length(one([for r in aws_wafv2_web_acl.main[0].rule : r if r.name == "loadtest-allow"]).action[0].allow) == 1 &&
      one([for r in aws_wafv2_web_acl.main[0].rule : r if r.name == "loadtest-allow"]).statement[0].ip_set_reference_statement[0].arn == aws_wafv2_ip_set.loadtest[0].arn
    )
    error_message = "loadtest-allow: priority 0, allow, referencing the loadtest IP set."
  }
  assert {
    condition = (
      aws_wafv2_ip_set.loadtest[0].addresses == toset(["${aws_eip.loadtest[0].public_ip}/32"]) &&
      aws_wafv2_ip_set.loadtest[0].scope == "CLOUDFRONT" &&
      aws_wafv2_ip_set.loadtest[0].ip_address_version == "IPV4"
    )
    error_message = "IP set holds only the EIP /32 (CLOUDFRONT, IPv4)."
  }
  assert {
    condition = (
      aws_instance.loadtest[0].instance_type == "t3.small" &&
      aws_instance.loadtest[0].metadata_options[0].http_tokens == "required" &&
      aws_instance.loadtest[0].root_block_device[0].encrypted == true &&
      aws_instance.loadtest[0].monitoring == true &&
      aws_instance.loadtest[0].subnet_id == aws_subnet.public[0].id
    )
    error_message = "Instance: t3.small, IMDSv2, encrypted root, detailed monitoring, public subnet 0."
  }
  assert {
    condition = (
      length(aws_security_group.loadtest[0].ingress) == 0 &&
      aws_vpc_security_group_egress_rule.loadtest_https[0].security_group_id == aws_security_group.loadtest[0].id &&
      aws_vpc_security_group_egress_rule.loadtest_https[0].ip_protocol == "tcp" &&
      aws_vpc_security_group_egress_rule.loadtest_https[0].from_port == 443 &&
      aws_vpc_security_group_egress_rule.loadtest_https[0].to_port == 443 &&
      aws_vpc_security_group_egress_rule.loadtest_https[0].cidr_ipv4 == "0.0.0.0/0"
    )
    error_message = "Load generator SG: no inbound, one egress rule tcp 443 to 0.0.0.0/0."
  }
  assert {
    condition = (
      aws_s3_bucket_public_access_block.loadtest_transfer[0].block_public_acls &&
      aws_s3_bucket_public_access_block.loadtest_transfer[0].block_public_policy &&
      aws_s3_bucket_public_access_block.loadtest_transfer[0].ignore_public_acls &&
      aws_s3_bucket_public_access_block.loadtest_transfer[0].restrict_public_buckets
    )
    error_message = "Transfer bucket must block all public access."
  }
}

run "paused_wins" {
  command = apply
  variables {
    paused           = true
    loadtest_enabled = true
  }

  assert {
    condition     = length(aws_instance.loadtest) == 0 && length(aws_wafv2_ip_set.loadtest) == 0
    error_message = "paused must override loadtest_enabled."
  }
}
