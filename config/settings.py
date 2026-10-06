"""
家計簿アプリの Django 設定。

秘密の情報や環境ごとに変わる値は、リポジトリに書かずに環境変数から読み込む（技術選定書 7.2 S-05）。
手元の開発では、リポジトリ直下の `.env` に書いておけば自動で読み込まれる（見本は `.env.example`）。
"""

from pathlib import Path

import django_stubs_ext
import environ

# ModelForm[TaxRate] のような型の書き方を、実行時にも使えるようにする（型チェックの mypy のため）
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parent.parent

# 環境変数の型と既定値。既定値は「安全側」にしておき、開発時だけ .env で緩める
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    PRODUCTION=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

# 本番では必ず環境変数で渡す。未設定なら起動時にエラーにして気づけるようにする
SECRET_KEY = env("SECRET_KEY")

# 本番で True にすると、エラー画面に設定値やコードが表示されてしまう
DEBUG = env("DEBUG")

ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# 本番（EC2 の Docker、Tailscale 経由の HTTPS）で動かすときだけ True にする（06 デプロイ設計書 1.3）
PRODUCTION = env("PRODUCTION")


# アプリケーションの定義
# 管理画面（django.contrib.admin）はログインがないため使わない（S-06）。
# 同じ理由で、利用者の認証（django.contrib.auth）も組み込まない（要件定義書 BR-01）。
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # このアプリの app（実装計画の分け方）
    "core",
    "masters",
    "ledger",
    "budgets",
    "recurring",
    "reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # CSS・JavaScript を Django から配信する（技術選定書 5章）
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                # 設定（テーマ・金額の表示など）を全テンプレートで使う
                "core.context_processors.app_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# データベース（MySQL 8.4。技術選定書 5.6）
# 接続先は環境変数 DATABASE_URL で渡す（例：mysql://利用者:パスワード@ホスト:ポート/DB名）
DATABASES = {"default": env.db("DATABASE_URL")}
# 日本語（絵文字を含む）を正しく扱うため、接続の文字コードを utf8mb4 にする
DATABASES["default"].setdefault("OPTIONS", {})["charset"] = "utf8mb4"


# 言語・タイムゾーン
# 日付は日本時間で扱う（要件定義書 BR-04）
LANGUAGE_CODE = "ja"

TIME_ZONE = "Asia/Tokyo"

USE_I18N = True

USE_TZ = True


# CSS・JavaScript・画像
STATIC_URL = "static/"
# collectstatic で集める先。本番のイメージを作るときに集める
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ログ（要件定義書 NF-OP-01・02）
# アプリのエラーと、定期処理（BT-01・02）の実行結果を出力する。
# 標準出力に出し、本番では Docker が CloudWatch Logs に送って30日で消す（06 デプロイ設計書 4.2）
# 本番の設定（06 デプロイ設計書 1.3）。CI でも PRODUCTION=True で check --deploy を通す（S-07）
if PRODUCTION:
    # ファイル名に中身のハッシュを付け、圧縮して配信する
    # （ブラウザに長く保存させても、更新が反映される）
    STORAGES["staticfiles"] = {"BACKEND": "core.storage.StaticFilesStorage"}
    # HTTPS は tailscale serve が受け、X-Forwarded-Proto: https を付けて Gunicorn に渡す。
    # Gunicorn は EC2 の中の 127.0.0.1 だけで待つため、
    # この見出しを偽って送れるのは tailscale serve だけ
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS]
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # HSTS の preload 一覧への登録は、ドメインの持ち主（Tailscale）が ts.net 全体で行っている。
    # 自分では登録できないため、preload を勧める警告（security.W021）は出さない
    SILENCED_SYSTEM_CHECKS = ["security.W021"]


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "{asctime} {levelname} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django": {"handlers": ["console"], "level": "WARNING", "propagate": False}},
}
