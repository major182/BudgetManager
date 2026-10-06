#!/bin/sh
# アプリのコンテナの起動（06 デプロイ設計書 4.2）
# 引数があれば、それを実行する（例：python manage.py register_recurring）
set -e

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# DB の表を最新にしてから、Gunicorn を起動する
python manage.py migrate --noinput
exec gunicorn config.wsgi:application --config /app/docker/app/gunicorn.conf.py
