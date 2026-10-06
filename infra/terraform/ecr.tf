# イメージの保管庫（06 デプロイ設計書 6章）。GitHub Actions が置き、EC2 が取り出す

resource "aws_ecr_repository" "app" {
  name = "${var.project_name}-app"

  image_scanning_configuration {
    scan_on_push = true # 置いたときに脆弱性を検査する（無料）
  }

  # latest のタグを置き直すため、上書きを許す
  image_tag_mutability = "MUTABLE"

  # terraform destroy のとき、イメージが残っていても消せるようにする
  force_delete = true
}

# 古いイメージは5つを残して消す（保管の量で課金されるため）。前の版に戻すときに使う分は残る
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep only the latest 5 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}
