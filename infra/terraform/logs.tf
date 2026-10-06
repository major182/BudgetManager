# アプリのログ（NF-OP-01・02、06 デプロイ設計書 4.2）。
# Docker の awslogs がコンテナの標準出力を送る。定期処理の結果も run-task.sh が同じ所へ出す

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.project_name}/app"
  retention_in_days = var.log_retention_days
}
