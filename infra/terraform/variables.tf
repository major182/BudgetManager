# 外から渡す値。実際の値は terraform.tfvars に書く（リポジトリに入れない）

variable "project_name" {
  description = "資源の名前の先頭に付ける名前。自動デプロイがデプロイ先を探すタグの値にもなる"
  type        = string
  default     = "budget"
}

variable "aws_region" {
  description = "資源を作るリージョン（NF-EN-03）"
  type        = string
  default     = "ap-northeast-1"
}

variable "tailnet_domain" {
  description = "Tailscale の tailnet の名前（例：tail1234.ts.net）。アプリの URL は https://budget.<この値>"
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]+[.]ts[.]net$", var.tailnet_domain))
    error_message = "tailnet_domain は xxxx.ts.net の形で書いてください。"
  }
}

variable "instance_type" {
  description = "EC2 の大きさ。t4g.micro は ARM・メモリ 1GB・$0.0108／時（06 デプロイ設計書 2.2）"
  type        = string
  default     = "t4g.micro"
}

variable "root_volume_size" {
  description = "EC2 のディスク（GB）。gp3 は $0.096／GB・月で、止めていてもかかる"
  type        = number
  default     = 10
}

variable "db_instance_class" {
  description = "RDS の大きさ。db.t4g.micro は $0.025／時"
  type        = string
  default     = "db.t4g.micro"
}

variable "db_engine_version" {
  description = "MySQL の版。開発（compose.yaml）・CI と同じ 8.4.11（技術選定書 4章）"
  type        = string
  default     = "8.4.11"
}

variable "db_allocated_storage" {
  description = "RDS のストレージ（GB）。20 が最小。gp3 は $0.138／GB・月で、止めていてもかかる"
  type        = number
  default     = 20
}

variable "db_backup_retention_days" {
  description = <<-EOT
    RDS の自動バックアップの保存日数。無料プランでは 1 が上限で、2 以上にすると
    FreeTierRestrictionError で作れない。7日分は S3 への書き出しで持つ（06 デプロイ設計書 7.5）
  EOT
  type        = number
  default     = 1
}

variable "db_deletion_protection" {
  description = "true の間は terraform destroy で RDS を消せない。課題が終わって消すときだけ false にする（06 デプロイ設計書 8章）"
  type        = bool
  default     = true
}

variable "backup_retention_days" {
  description = "S3 のバックアップを残す日数（NF-AV-03）"
  type        = number
  default     = 7
}

variable "log_retention_days" {
  description = "CloudWatch Logs のログを残す日数（NF-OP-01）"
  type        = number
  default     = 30
}

variable "github_repository" {
  description = "自動デプロイを許すリポジトリ（オーナー名/リポジトリ名）"
  type        = string
  default     = "major182/BudgetManager"
}

variable "github_owner_id" {
  description = <<-EOT
    GitHub のオーナーの数値 ID。GitHub は OIDC の識別子に数値 ID を含めて送ってくるため、
    名前だけで照合すると認証が拒否される（06 デプロイ設計書 6.3）。
    調べ方：gh api repos/major182/BudgetManager --jq '.owner.id'
  EOT
  type        = string
  default     = "329081291"
}

variable "github_repository_id" {
  description = "GitHub のリポジトリの数値 ID。調べ方：gh api repos/major182/BudgetManager --jq '.id'"
  type        = string
  default     = "1397027071"
}
