# データベース（RDS for MySQL。06 デプロイ設計書 1.1）

resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db"
  subnet_ids = [for s in aws_subnet.private : s.id]

  tags = { Name = "${var.project_name}-db" }
}

# パスワードは Terraform が作り、パラメータストアの DATABASE_URL に入れる（ssm.tf）。
# 接続の URL に入れるため、記号を使わない
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_db_instance" "main" {
  identifier = "${var.project_name}-db"

  engine         = "mysql"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  db_name  = "budget"
  username = "budget"
  password = random_password.db.result
  port     = 3306

  allocated_storage = var.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false # NF-SE-03
  multi_az               = false

  backup_retention_period = var.db_backup_retention_days
  backup_window           = "18:00-19:00"         # UTC。日本時間の 3:00〜4:00
  maintenance_window      = "sun:19:00-sun:20:00" # UTC。日本時間の 月曜 4:00〜5:00

  # マイナーな更新（8.4.x）は自動で当てる。脆弱性の修正のため
  auto_minor_version_upgrade = true

  # 削除するときは、先に S3 のバックアップを手元に保存する手順にしている（06 デプロイ設計書 8章）
  skip_final_snapshot = true
  deletion_protection = var.db_deletion_protection

  tags = { Name = "${var.project_name}-db" }

  lifecycle {
    # 自動で当たったマイナーな更新（8.4.12 など）を、次の apply で戻そうとしない
    ignore_changes = [engine_version]
  }
}
