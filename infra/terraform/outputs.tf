# apply のあとに表示する値。terraform output でいつでも見られる

output "app_url" {
  description = "アプリの URL（Tailscale を起動した端末からだけ開ける）"
  value       = "https://${local.app_host}/"
}

output "instance_id" {
  description = "EC2 のインスタンス ID（起動・停止・SSM で入るときに使う）"
  value       = aws_instance.app.id
}

output "db_identifier" {
  description = "RDS の識別子（起動・停止のときに使う）"
  value       = aws_db_instance.main.identifier
}

output "ecr_repository_url" {
  description = "イメージの置き場"
  value       = aws_ecr_repository.app.repository_url
}

output "backup_bucket" {
  description = "バックアップの置き場"
  value       = aws_s3_bucket.backup.bucket
}

output "github_actions_role_arn" {
  description = "GitHub の Secret AWS_ROLE_ARN に登録する値（06 デプロイ設計書 6.3）"
  value       = aws_iam_role.github_actions.arn
}
