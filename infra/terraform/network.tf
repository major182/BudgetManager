# ネットワーク（06 デプロイ設計書 1.2）

resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"

  # RDS の接続先の名前を引くために、VPC の中の名前解決を有効にする
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project_name}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project_name}-igw" }
}

data "aws_availability_zones" "available" {
  state = "available"
}

# ---------- パブリックサブネット（EC2） ----------
# EC2 は Tailscale・ECR・SSM へ外向きにつなぐため、インターネットへの経路を持たせる。
# 受け付ける口はセキュリティグループで1つも開けない
resource "aws_subnet" "public" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]

  # 自動で公開 IP を割り当てる。止めると手放すため、止めている間は課金されない（Elastic IP は使わない）
  map_public_ip_on_launch = true

  tags = { Name = "${var.project_name}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${var.project_name}-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ---------- プライベートサブネット（RDS） ----------
# インターネットへの経路を持たない（NF-SE-03）。
# RDS は単一 AZ でも「2つの AZ にまたがるサブネットの組」を求めるため、2つ作る（片方は空のまま）
resource "aws_subnet" "private" {
  for_each = {
    a = { cidr = "10.0.11.0/24", az_index = 0 }
    c = { cidr = "10.0.12.0/24", az_index = 1 }
  }

  vpc_id                  = aws_vpc.main.id
  cidr_block              = each.value.cidr
  availability_zone       = data.aws_availability_zones.available.names[each.value.az_index]
  map_public_ip_on_launch = false

  tags = { Name = "${var.project_name}-private-${each.key}" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  # 空にして、VPC の中（local）以外への経路を持たないことを Terraform に管理させる
  route = []

  tags = { Name = "${var.project_name}-private" }
}

resource "aws_route_table_association" "private" {
  for_each = aws_subnet.private

  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

# ---------- EC2 のセキュリティグループ ----------
# 受信の規則は1つも書かない（NF-SE-01）。アプリには Tailscale を通してだけ届く。
# Tailscale はサーバーから外へつないで通信路を作るため、受け付ける口が要らない
resource "aws_security_group" "app" {
  name        = "${var.project_name}-app"
  description = "Application server: no inbound rules (reached only through Tailscale)"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-app" }
}

# 送信はすべて許す（Tailscale・ECR・SSM・CloudWatch Logs・S3・OS の更新・祝日データの取得）
resource "aws_vpc_security_group_egress_rule" "app_all" {
  security_group_id = aws_security_group.app.id
  description       = "Allow all outbound traffic"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# ---------- RDS のセキュリティグループ ----------
resource "aws_security_group" "db" {
  name        = "${var.project_name}-db"
  description = "Database: MySQL from the application server only"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project_name}-db" }
}

# EC2 のセキュリティグループからの 3306番だけを許す。IP ではなく役割で許すため、EC2 を作り直しても直さなくてよい
resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  security_group_id            = aws_security_group.db.id
  description                  = "MySQL from the application server"
  referenced_security_group_id = aws_security_group.app.id
  from_port                    = 3306
  to_port                      = 3306
  ip_protocol                  = "tcp"
}
