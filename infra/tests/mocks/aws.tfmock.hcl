# Shared by every test file: the mock provider's random strings fail the
# provider's ARN validation wherever one resource's ARN feeds another.
mock_resource "aws_lb" {
  defaults = {
    arn = "arn:aws:elasticloadbalancing:ap-southeast-1:420974348257:loadbalancer/app/prompt-patrol/0123456789abcdef"
  }
}

mock_resource "aws_lb_target_group" {
  defaults = {
    arn = "arn:aws:elasticloadbalancing:ap-southeast-1:420974348257:targetgroup/prompt-patrol-api/0123456789abcdef"
  }
}

mock_resource "aws_cloudfront_function" {
  defaults = {
    arn = "arn:aws:cloudfront::420974348257:function/prompt-patrol-spa-rewrite"
  }
}

mock_resource "aws_iam_role" {
  defaults = {
    arn = "arn:aws:iam::420974348257:role/prompt-patrol-mock"
  }
}

mock_resource "aws_ecs_cluster" {
  defaults = {
    arn = "arn:aws:ecs:ap-southeast-1:420974348257:cluster/prompt-patrol"
  }
}

mock_resource "aws_ecs_task_definition" {
  defaults = {
    arn = "arn:aws:ecs:ap-southeast-1:420974348257:task-definition/prompt-patrol-api:1"
  }
}

mock_resource "aws_service_discovery_service" {
  defaults = {
    arn = "arn:aws:servicediscovery:ap-southeast-1:420974348257:service/srv-0123456789abcdef"
  }
}

mock_resource "aws_acm_certificate" {
  defaults = {
    arn = "arn:aws:acm:us-east-1:420974348257:certificate/00000000-0000-0000-0000-000000000000"
    domain_validation_options = [{
      domain_name           = "app.prompt-patrol.com"
      resource_record_name  = "_x.app.prompt-patrol.com."
      resource_record_type  = "CNAME"
      resource_record_value = "_y.acm-validations.aws."
    }]
  }
}

mock_resource "aws_acm_certificate_validation" {
  defaults = {
    certificate_arn = "arn:aws:acm:us-east-1:420974348257:certificate/00000000-0000-0000-0000-000000000000"
  }
}

mock_data "aws_route53_zone" {
  defaults = {
    zone_id = "Z0734110WU65K27G8SYH"
  }
}
