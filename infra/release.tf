# Release state shared with the GitHub deploy pipeline.
# - image-tag: the commit SHA currently live. Terraform seeds it once; after
#   that the pipeline owns it (writes it on every deploy), so ignore_changes
#   stops an apply from rolling the SHA back.
# - cloudfront-distribution-id: Terraform owns it; the pipeline only reads it
#   so the invalidation job never hardcodes the id.

# insecure_value, not value: value is sensitive and would hide task definition
# diffs in plans, and the provider only reads back the attribute you set.
resource "aws_ssm_parameter" "image_tag" {
  name           = "/prompt-patrol/image-tag"
  type           = "String"
  insecure_value = "a2a782713e3e97ecd9ccef576a63a9cfaa11aaf5"

  lifecycle {
    ignore_changes = [insecure_value]
  }
}

# Refresh records the pipeline's value in state and ignore_changes keeps the
# config from reverting it, so this is always the live SHA. No data source: on
# the first apply it would be unknown and replace all three task definitions.
locals {
  image_tag = aws_ssm_parameter.image_tag.insecure_value
}

resource "aws_ssm_parameter" "cloudfront_distribution_id" {
  name  = "/prompt-patrol/cloudfront-distribution-id"
  type  = "String"
  value = aws_cloudfront_distribution.web.id
}
