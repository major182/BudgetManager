# DB のバックアップの置き場（NF-AV-03、06 デプロイ設計書 7.5）。
# 無料プランでは RDS の自動バックアップを1日しか残せないため、毎日の書き出しを S3 に7日残す

resource "aws_s3_bucket" "backup" {
  bucket = "${var.project_name}-backup-${data.aws_caller_identity.current.account_id}"

  # terraform destroy のとき、中のバックアップごと消す。残したいものは先に手元へ保存する（06 デプロイ設計書 8章）
  force_destroy = true
}

# 公開の設定をすべて禁止する
resource "aws_s3_bucket_public_access_block" "backup" {
  bucket = aws_s3_bucket.backup.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 保存するファイルを暗号化する（S3 が管理する鍵。無料）
resource "aws_s3_bucket_server_side_encryption_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 7日たったファイルを自動で消す
resource "aws_s3_bucket_lifecycle_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id

  rule {
    id     = "expire-old-backups"
    status = "Enabled"
    filter {}

    expiration {
      days = var.backup_retention_days
    }
  }
}
