# Auth0 sends the invite / password emails through SES so they come from our
# domain. Same Region as everything else, so mail stays in Singapore.
#
# DKIM alone gives DMARC alignment, so no custom MAIL FROM: SPF passes on
# SES's own amazonses.com return path. DMARC starts at p=none (monitor only);
# tighten to quarantine once real mail is seen passing.

locals {
  email_from = "no-reply@prompt-patrol.com"
}

resource "aws_sesv2_email_identity" "domain" {
  email_identity = data.aws_route53_zone.main.name

  # SES's default key length; declared so the test mocks can fill in the tokens.
  dkim_signing_attributes {
    next_signing_key_length = "RSA_2048_BIT"
  }
}

# Easy DKIM always issues exactly three tokens.
resource "aws_route53_record" "dkim" {
  count   = 3
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "${aws_sesv2_email_identity.domain.dkim_signing_attributes[0].tokens[count.index]}._domainkey"
  type    = "CNAME"
  records = ["${aws_sesv2_email_identity.domain.dkim_signing_attributes[0].tokens[count.index]}.dkim.amazonses.com"]
  ttl     = 1800
}

resource "aws_route53_record" "dmarc" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "_dmarc"
  type    = "TXT"
  records = ["v=DMARC1; p=none;"]
  ttl     = 1800
}

# Auth0's SES integration only takes a static access key, so this is the one
# IAM user in the account: a machine principal, not a human. It can send only
# as local.email_from through this identity. The access key is created by hand
# (`aws iam create-access-key`) and pasted straight into Auth0, so it never
# lands in Terraform state.
resource "aws_iam_user" "auth0_ses" {
  name = "prompt-patrol-auth0-ses"
}

resource "aws_iam_user_policy" "auth0_ses_send" {
  name = "send-as-no-reply"
  user = aws_iam_user.auth0_ses.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = ["ses:SendEmail", "ses:SendRawEmail"]
      Resource  = aws_sesv2_email_identity.domain.arn
      Condition = { StringEquals = { "ses:FromAddress" = local.email_from } }
    }]
  })
}
