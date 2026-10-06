"""Gunicorn の設定（06 デプロイ設計書 4.2）。"""

# コンテナの中では全体で待ち、外へは EC2 の 127.0.0.1:8000 だけに出す
# （docker run -p 127.0.0.1:8000:8000）
bind = "0.0.0.0:8000"  # noqa: S104
# t4g.micro（メモリ 1GB）に収まる数
workers = 2
timeout = 30
# アクセスのログもエラーも標準出力に出す（Docker が CloudWatch Logs に送る）
accesslog = "-"
errorlog = "-"
