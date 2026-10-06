# アプリの環境変数（06 デプロイ設計書 3.1）。
# EC2 は起動のたびに /budget/ の下を読み、/opt/budget/app.env を作り直す（load-env.sh）。
# Tailscale の認証キー（/budget/TAILSCALE_AUTHKEY）は利用者が登録するため、ここでは作らない

locals {
  app_host = "${var.project_name}.${var.tailnet_domain}"
}

# Django の秘密の鍵（S-05）。docker の --env-file にそのまま書けるよう、記号を使わない
resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "aws_ssm_parameter" "secret_key" {
  name  = "/${var.project_name}/SECRET_KEY"
  type  = "SecureString"
  value = random_password.secret_key.result
}

resource "aws_ssm_parameter" "database_url" {
  name  = "/${var.project_name}/DATABASE_URL"
  type  = "SecureString"
  value = "mysql://${aws_db_instance.main.username}:${random_password.db.result}@${aws_db_instance.main.address}:${aws_db_instance.main.port}/${aws_db_instance.main.db_name}"
}

resource "aws_ssm_parameter" "allowed_hosts" {
  name  = "/${var.project_name}/ALLOWED_HOSTS"
  type  = "String"
  value = local.app_host
}
