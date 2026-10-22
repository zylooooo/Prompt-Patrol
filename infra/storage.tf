# Uploaded batch CSVs. Storage only, so not gated on var.paused. Encryption
# (SSE-S3) and BucketOwnerEnforced are the S3 defaults for new buckets, so no
# resource is needed for either. CORS is for the browser's direct presigned PUT.

locals {
  # Change the CSV retention days to the confirmed number after checking the PDPA
  # constraints.
  csv_retention_days = 60
}

resource "aws_s3_bucket" "batches" {
  bucket        = "prompt-patrol-batches-420974348257"
  force_destroy = true # so the end-of-project destroy works with objects inside
}

resource "aws_s3_bucket_public_access_block" "batches" {
  bucket                  = aws_s3_bucket.batches.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "batches" {
  bucket = aws_s3_bucket.batches.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.batches.arn, "${aws_s3_bucket.batches.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.batches]
}

resource "aws_s3_bucket_lifecycle_configuration" "batches" {
  bucket = aws_s3_bucket.batches.id

  rule {
    id     = "expire-csvs"
    status = "Enabled"

    filter {}

    expiration {
      days = local.csv_retention_days
    }
  }
}

# The SPA PUTs the CSV straight to S3 via a presigned URL. Only the frontend
# origin, only PUT, only content-type: the presigned signature covers the rest.
resource "aws_s3_bucket_cors_configuration" "batches" {
  bucket = aws_s3_bucket.batches.id

  cors_rule {
    allowed_origins = [local.frontend_url]
    allowed_methods = ["PUT"]
    allowed_headers = ["content-type"]
    max_age_seconds = 3000
  }
}
