# Four tiers per AZ. Only the egress tier (API tasks) routes to the NAT, for
# Auth0; everything else has no internet route. Routes are per subnet, so the
# tiers have to be separate subnets: a NAT cannot filter destinations.
locals {
  azs = ["ap-southeast-1a", "ap-southeast-1b"]
}

resource "aws_vpc" "main" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true # both required for interface endpoints' private DNS
  enable_dns_hostnames = true

  tags = { Name = "prompt-patrol" }
}

# Strip the default SG's allow-all rules so nothing can fall back to it.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "prompt-patrol" }
}

# --- Subnets -----------------------------------------------------------------

resource "aws_subnet" "public" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = "10.20.${count.index}.0/24"
  tags              = { Name = "prompt-patrol-public-${local.azs[count.index]}", Tier = "public" }
}

resource "aws_subnet" "egress" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = "10.20.${10 + count.index}.0/24"
  tags              = { Name = "prompt-patrol-egress-${local.azs[count.index]}", Tier = "egress" }
}

resource "aws_subnet" "isolated" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = "10.20.${20 + count.index}.0/24"
  tags              = { Name = "prompt-patrol-isolated-${local.azs[count.index]}", Tier = "isolated" }
}

resource "aws_subnet" "database" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = "10.20.${30 + count.index}.0/24"
  tags              = { Name = "prompt-patrol-database-${local.azs[count.index]}", Tier = "database" }
}

# --- NAT (hourly-billed: removed when paused) ---------------------------------

# ponytail: one NAT in zone a. A zone-a outage blocks new logins (Auth0
# unreachable); existing sessions keep working. Add a NAT per AZ if that matters.
resource "aws_eip" "nat" {
  count  = var.paused ? 0 : 1
  domain = "vpc"
  tags   = { Name = "prompt-patrol-nat" }
}

resource "aws_nat_gateway" "main" {
  count         = var.paused ? 0 : 1
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id
  tags          = { Name = "prompt-patrol" }

  depends_on = [aws_internet_gateway.main]
}

# --- Route tables --------------------------------------------------------------

# The VPC's auto-created main table: adopted so it's tagged and stays empty.
# Every subnet is explicitly associated below; any that isn't lands here,
# with no route out.
resource "aws_default_route_table" "main" {
  default_route_table_id = aws_vpc.main.default_route_table_id
  route                  = []
  tags                   = { Name = "prompt-patrol-main-unused" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "prompt-patrol-public" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table" "egress" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "prompt-patrol-egress" }
}

resource "aws_route" "egress_nat" {
  count                  = var.paused ? 0 : 1
  route_table_id         = aws_route_table.egress.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main[0].id
}

# Isolated + database tiers. `route = []` makes Terraform remove any route
# added by hand, so this table can't quietly gain an internet path. (The S3
# gateway endpoint's route is managed by the endpoint and isn't affected.)
resource "aws_route_table" "isolated" {
  vpc_id = aws_vpc.main.id
  route  = []
  tags   = { Name = "prompt-patrol-isolated" }
}

resource "aws_route_table_association" "public" {
  count          = length(local.azs)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "egress" {
  count          = length(local.azs)
  subnet_id      = aws_subnet.egress[count.index].id
  route_table_id = aws_route_table.egress.id
}

resource "aws_route_table_association" "isolated" {
  count          = length(local.azs)
  subnet_id      = aws_subnet.isolated[count.index].id
  route_table_id = aws_route_table.isolated.id
}

resource "aws_route_table_association" "database" {
  count          = length(local.azs)
  subnet_id      = aws_subnet.database[count.index].id
  route_table_id = aws_route_table.isolated.id
}
