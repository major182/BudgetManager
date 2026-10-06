# 本番のイメージ（06 デプロイ設計書 4.2）。EC2（ARM）でも手元（x86）でも同じ Dockerfile で作れる
# 起動：migrate → Gunicorn。CSS・JavaScript は WhiteNoise が配信する

# ---------------------------------------------------------------- 依存のインストール
FROM python:3.14.7-slim-trixie AS build

# mysqlclient のビルドに必要なもの（Linux 用のビルド済みのパッケージがないため）
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=astral/uv:0.12.21 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# 依存だけを先に入れ、コードの変更でこの層を作り直さないようにする
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
# 静的ファイルを集める。設定の読み込みに必要な値は、この場限りのダミー
RUN SECRET_KEY=build-only DATABASE_URL=mysql://x:x@localhost/x PRODUCTION=True \
    .venv/bin/python manage.py collectstatic --noinput

# ---------------------------------------------------------------- 実行用
FROM python:3.14.7-slim-trixie

# mysqlclient の実行に必要なライブラリだけを入れる
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmariadb3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home app

WORKDIR /app
COPY --from=build /app /app

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PRODUCTION=True
USER app
EXPOSE 8000
ENTRYPOINT ["/app/docker/app/entrypoint.sh"]
