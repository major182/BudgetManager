#!/bin/bash
# EC2 の初期設定（06 デプロイ設計書 4.1）。EC2 を作ったときに1回だけ動く。
# Terraform の templatefile が $${名前} を値に置き換えるため、シェルの変数は $NAME の形で書く。
# シェルの $${...} を使うときは、$ を2つ重ねて書く（templatefile が1つにして残す）
# 実行の記録：/var/log/user-data.log
set -euxo pipefail
exec > >(tee /var/log/user-data.log) 2>&1

REGION=${aws_region}
APP_DIR=/opt/${project}

# ---------------------------------------------------------------- OS
# cron を日本時間で動かす
timedatectl set-timezone Asia/Tokyo

# メモリ 1GB での起動時の不足を防ぐため、スワップを 1GB 作る
dd if=/dev/zero of=/swapfile bs=1M count=1024
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo "/swapfile swap swap defaults 0 0" >> /etc/fstab

dnf install -y docker cronie
systemctl enable --now docker crond

# ---------------------------------------------------------------- Tailscale（06 デプロイ設計書 3.2）
dnf config-manager --add-repo https://pkgs.tailscale.com/stable/amazon-linux/2023/tailscale.repo
dnf install -y tailscale-1.102.5
systemctl enable --now tailscaled

# 認証キーは利用者がパラメータストアに登録したもの。使い捨てのため、参加したあとは不要になる。
# キーを扱う間はコマンドの記録（set -x）を止める。止めないと、キーがログと EC2 のコンソールの出力に残る（NF-SE-04）
set +x
AUTHKEY=$(aws ssm get-parameter --region "$REGION" --name /${project}/TAILSCALE_AUTHKEY \
  --with-decryption --query Parameter.Value --output text)
tailscale up --authkey="$AUTHKEY" --hostname=${project}
unset AUTHKEY
set -x

# tailnet の中だけに HTTPS で公開し、Gunicorn（127.0.0.1:8000）へ渡す。設定は再起動しても残る
tailscale serve --bg --https=443 http://127.0.0.1:8000

# ---------------------------------------------------------------- スクリプト
mkdir -p "$APP_DIR"

# パラメータストアの /budget/ の下（認証キーを除く）から、アプリの環境変数のファイルを作る
cat > "$APP_DIR/load-env.sh" <<'SCRIPT'
#!/bin/bash
set -euo pipefail
umask 077
aws ssm get-parameters-by-path --region ${aws_region} --path /${project}/ --with-decryption \
  --query "Parameters[?Name!='/${project}/TAILSCALE_AUTHKEY'].[Name,Value]" --output text \
  | while IFS=$'\t' read -r name value; do echo "$(basename "$name")=$value"; done \
  > /opt/${project}/app.env.tmp
mv /opt/${project}/app.env.tmp /opt/${project}/app.env
SCRIPT

# イメージを取り出してコンテナを入れ替え、応答を確かめる（06 デプロイ設計書 6.2）。
# 引数でタグを選べる（前の版に戻すときはコミット ID）
cat > "$APP_DIR/deploy.sh" <<'SCRIPT'
#!/bin/bash
set -euo pipefail
TAG=$${1:-latest}
IMAGE=${ecr_repository}:$TAG
HOST=$(grep '^ALLOWED_HOSTS=' /opt/${project}/app.env | cut -d= -f2)

aws ecr get-login-password --region ${aws_region} \
  | docker login --username AWS --password-stdin ${ecr_registry}
docker pull "$IMAGE"

docker rm -f app 2>/dev/null || true
docker run -d --name app --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  --env-file /opt/${project}/app.env \
  --log-driver awslogs \
  --log-opt awslogs-region=${aws_region} \
  --log-opt awslogs-group=${log_group} \
  --log-opt awslogs-stream=app \
  "$IMAGE"

# tailscale serve と同じ見出しを付けて、応答があるまで最大 60 秒待つ
for _ in $(seq 1 30); do
  if curl -fsS -o /dev/null -H "Host: $HOST" -H "X-Forwarded-Proto: https" http://127.0.0.1:8000/; then
    echo "デプロイしました：$IMAGE"
    # 動いている版以外のアプリのイメージを消す（ディスク 10GB を圧迫しないため）。
    # 古いイメージにはコミット ID のタグが残るため、タグのないものだけを消す prune では消えない。
    # 前の版に戻すときは、ECR から取り出し直す（ECR には5つ残している）
    CURRENT=$(docker inspect --format '{{.Image}}' app)
    # 消すものがないと grep が失敗の終わり方をするため、|| true で続ける（set -o pipefail のため）
    docker images --no-trunc --format '{{.ID}}' ${ecr_repository} | sort -u \
      | { grep -vF "$CURRENT" || true; } | xargs -r docker rmi -f
    docker image prune -f
    exit 0
  fi
  sleep 2
done
echo "アプリが応答しません。docker logs app で確かめてください" >&2
exit 1
SCRIPT

# アプリのコンテナで管理コマンドを動かし、出力をコンテナのログ（→ CloudWatch Logs）に送る（NF-OP-02）
cat > "$APP_DIR/run-task.sh" <<'SCRIPT'
#!/bin/bash
set -euo pipefail
docker exec app sh -c 'python manage.py "$@" > /proc/1/fd/1 2>&1' sh "$@"
SCRIPT

# DB を書き出して圧縮し、S3 に置く（NF-AV-03）。S3 の規則で7日たつと消える
cat > "$APP_DIR/backup.sh" <<'SCRIPT'
#!/bin/bash
set -euo pipefail
URL=$(grep '^DATABASE_URL=' /opt/${project}/app.env | cut -d= -f2-)
DB_USER=$(echo "$URL" | sed -E 's#^mysql://([^:]+):.*#\1#')
DB_PASS=$(echo "$URL" | sed -E 's#^mysql://[^:]+:([^@]+)@.*#\1#')
DB_HOST=$(echo "$URL" | sed -E 's#^.*@([^:/]+).*#\1#')
DB_NAME=$(echo "$URL" | sed -E 's#^.*/([^/?]+)$#\1#')
FILE=$DB_NAME-$(date +%Y%m%d-%H%M).sql.gz

docker run --rm -e MYSQL_PWD="$DB_PASS" mysql:8.4.11 \
  mysqldump -h "$DB_HOST" -u "$DB_USER" --single-transaction --no-tablespaces --set-gtid-purged=OFF "$DB_NAME" \
  | gzip | aws s3 cp - "s3://${backup_bucket}/$FILE"
echo "バックアップしました：$FILE"
SCRIPT

# S3 のバックアップから DB を戻す。戻す間はアプリを止める（06 デプロイ設計書 7.5）
cat > "$APP_DIR/restore.sh" <<'SCRIPT'
#!/bin/bash
set -euo pipefail
FILE=$1
URL=$(grep '^DATABASE_URL=' /opt/${project}/app.env | cut -d= -f2-)
DB_USER=$(echo "$URL" | sed -E 's#^mysql://([^:]+):.*#\1#')
DB_PASS=$(echo "$URL" | sed -E 's#^mysql://[^:]+:([^@]+)@.*#\1#')
DB_HOST=$(echo "$URL" | sed -E 's#^.*@([^:/]+).*#\1#')
DB_NAME=$(echo "$URL" | sed -E 's#^.*/([^/?]+)$#\1#')

docker stop app
aws s3 cp "s3://${backup_bucket}/$FILE" - | gunzip \
  | docker run --rm -i -e MYSQL_PWD="$DB_PASS" mysql:8.4.11 mysql -h "$DB_HOST" -u "$DB_USER" "$DB_NAME"
docker start app
echo "戻しました：$FILE"
SCRIPT

chmod 700 "$APP_DIR"/*.sh

# ---------------------------------------------------------------- 起動のたびに動かす（06 デプロイ設計書 4.1）
cat > /etc/systemd/system/${project}.service <<'UNIT'
[Unit]
Description=Budget app: load settings and start the container
After=network-online.target docker.service tailscaled.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/opt/${project}/load-env.sh
ExecStart=/opt/${project}/deploy.sh

[Install]
WantedBy=multi-user.target
UNIT

# ---------------------------------------------------------------- 定期処理（06 デプロイ設計書 4.3、日本時間）
cat > /etc/cron.d/${project} <<'CRON'
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
# BT-01 定期収支の自動登録
5 0 * * * root /opt/${project}/run-task.sh register_recurring
# NF-AV-03 バックアップ
30 0 * * * root /opt/${project}/backup.sh 2>&1 | logger -t ${project}-backup
# BT-02 祝日データの更新（1月と12月）
0 1 1 1,12 * root /opt/${project}/run-task.sh import_holidays
# 止めていた日の分の定期収支を、起動のあとに登録する
@reboot root sleep 180 && /opt/${project}/run-task.sh register_recurring
CRON

systemctl daemon-reload
systemctl enable ${project}.service
# 初回はイメージがまだ ECR にないことがある。失敗しても初期設定は続け、イメージを置いてから deploy.sh を動かす
systemctl start ${project}.service || echo "アプリの起動は、イメージを ECR に置いてから行います"
