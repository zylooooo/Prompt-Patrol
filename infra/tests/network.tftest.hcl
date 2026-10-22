# Offline: the mock provider fakes every AWS call, so this runs in CI without
# credentials. It checks the configuration's intent, not live AWS.
mock_provider "aws" {
  source = "./tests/mocks"
}

mock_provider "aws" {
  alias  = "us_east_1"
  source = "./tests/mocks"
}

run "running" {
  command = apply

  # Explicit: `terraform test` also loads terraform.tfvars, which may be paused.
  variables {
    paused = false
  }

  assert {
    condition     = length(aws_route_table.isolated.route) == 0
    error_message = "The isolated/database route table must have no routes."
  }

  assert {
    condition     = aws_route.egress_nat[0].route_table_id == aws_route_table.egress.id
    error_message = "The NAT route must be on the egress route table only."
  }

  assert {
    condition     = alltrue([for a in concat(aws_route_table_association.isolated, aws_route_table_association.database) : a.route_table_id == aws_route_table.isolated.id])
    error_message = "Isolated and database subnets must use the isolated route table."
  }

  assert {
    condition     = length(aws_vpc_endpoint.interface) == 5
    error_message = "Expected 5 interface endpoints."
  }

  assert {
    condition     = alltrue([for e in aws_vpc_endpoint.interface : e.private_dns_enabled && length(e.subnet_ids) == 2 && alltrue([for s in aws_subnet.isolated : contains(e.subnet_ids, s.id)])])
    error_message = "Interface endpoints must have private DNS on and sit in both isolated subnets."
  }
}

run "paused" {
  command = apply

  variables {
    paused = true
  }

  assert {
    condition     = length(aws_nat_gateway.main) + length(aws_eip.nat) + length(aws_route.egress_nat) + length(aws_vpc_endpoint.interface) == 0
    error_message = "Paused must remove the NAT, its EIP and route, and all interface endpoints."
  }

  assert {
    condition     = length(aws_subnet.public) + length(aws_subnet.egress) + length(aws_subnet.isolated) + length(aws_subnet.database) == 8
    error_message = "Paused must keep all subnets (free, and later steps depend on them)."
  }
}
