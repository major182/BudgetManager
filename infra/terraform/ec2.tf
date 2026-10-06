# アプリのサーバー（06 デプロイ設計書 1.1・4章）

# 最新の Amazon Linux 2023（ARM）。AWS が公開しているパラメータから引く
data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_instance" "app" {
  ami                    = data.aws_ssm_parameter.al2023_arm64.value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  # 初期設定（作ったときに1回だけ動く）。秘密の値は渡さず、パラメータストアの場所だけを渡す
  user_data = templatefile("${path.module}/user_data.sh", {
    aws_region     = var.aws_region
    project        = var.project_name
    ecr_registry   = split("/", aws_ecr_repository.app.repository_url)[0]
    ecr_repository = aws_ecr_repository.app.repository_url
    log_group      = aws_cloudwatch_log_group.app.name
    backup_bucket  = aws_s3_bucket.backup.bucket
  })

  # user_data を変えたら作り直す。作り直すと Tailscale の認証キーが要る（06 デプロイ設計書 3.2）
  user_data_replace_on_change = true

  root_block_device {
    volume_size = var.root_volume_size
    volume_type = "gp3"
    encrypted   = true
  }

  # インスタンスの情報の取得を IMDSv2 に限る（SSRF で認証情報を盗まれる経路を断つ）
  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  tags = { Name = "${var.project_name}-app" }

  lifecycle {
    # AMI は新しい版が出るたびに値が変わる。そのたびに作り直さないよう、作ったときの版のままにする。
    # OS の更新は、サーバーの中の dnf で当てる
    ignore_changes = [ami]
  }

  # 起動時にアプリの環境変数を読むため、パラメータストアの値（DB の接続先を含む）がそろってから作る。
  # そろう前に起動すると DATABASE_URL がなく、アプリが再起動を繰り返す（初回の構築で起きた）
  depends_on = [
    aws_internet_gateway.main,
    aws_ssm_parameter.secret_key,
    aws_ssm_parameter.database_url,
    aws_ssm_parameter.allowed_hosts,
  ]
}

# ---------- EC2 の権限（IAM ロール） ----------
data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "${var.project_name}-ec2"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-ec2"
  role = aws_iam_role.ec2.name
}

# SSM Session Manager で入る・自動デプロイのコマンドを受ける
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# ECR からイメージを取り出す
resource "aws_iam_role_policy_attachment" "ecr_read" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

data "aws_iam_policy_document" "ec2_app" {
  # パラメータストアの /budget/ の下だけを読む（SecureString の復号は、AWS が管理する鍵の既定の権限で行える）
  statement {
    actions = ["ssm:GetParameter", "ssm:GetParametersByPath"]
    resources = [
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}",
      "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/*",
    ]
  }

  # ログを送る
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }

  # バックアップを置く・戻すときに取り出す
  statement {
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.backup.arn}/*"]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.backup.arn]
  }
}

resource "aws_iam_role_policy" "ec2_app" {
  name   = "${var.project_name}-app"
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.ec2_app.json
}
