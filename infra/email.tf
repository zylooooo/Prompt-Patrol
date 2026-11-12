# Auth0 sends the invite / password emails through Resend from the subdomain
# mail.prompt-patrol.com (Tokyo region, the closest to Singapore). The
# subdomain keeps Resend's records off the root. The Resend API key lives only
# in Auth0 > Branding > Email Provider, never in Terraform state or Secrets
# Manager. Values below are copied from Resend > Domains; if Resend re-issues
# them (e.g. the domain is deleted and re-added), update them here.
#
# DMARC starts at p=none (monitor only); it covers the subdomain too. Tighten
# to quarantine once real mail is seen passing.

resource "aws_route53_record" "resend_dkim" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "resend._domainkey.mail"
  type    = "TXT"
  records = ["p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC1b6uCgQtxlOEoJmXwYzxEvge/WhTpsq3m5Q2ixn8A7guMu6ea5fTk0JS8DmUXVeawXULTEpJrVA95z/qHofJh/IO6P8ebcHMgJK1Ozq0j8IqytkFNqgRHsK344AI1uCE3WT/coNHd/1Hm+7/4vNTmoYeDYTGM7cWoctmQWzyRWQIDAQAB"]
  ttl     = 1800
}

# Resend's SPF / return-path records. Two CNAMEs, not the older MX + TXT pair.
resource "aws_route53_record" "resend_spf" {
  for_each = {
    "rsend.mail" = "rsend-apne1.forge.rmta.net"
    "send.mail"  = "send.forge.rmta.net"
  }
  zone_id = data.aws_route53_zone.main.zone_id
  name    = each.key
  type    = "CNAME"
  records = [each.value]
  ttl     = 1800
}

resource "aws_route53_record" "dmarc" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "_dmarc"
  type    = "TXT"
  records = ["v=DMARC1; p=none;"]
  ttl     = 1800
}
