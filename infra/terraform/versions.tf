# Terraform 本体とプロバイダーの版を固定する（技術選定書 3.4）

terraform {
  required_version = "1.16.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.67.0"
    }
    # DB のパスワードと Django の秘密の鍵を作る
    random = {
      source  = "hashicorp/random"
      version = "3.9.1"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # すべての資源に付けるタグ。請求の画面で見分けられ、自動デプロイがデプロイ先を探すのにも使う
  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "Terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
