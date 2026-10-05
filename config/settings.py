"""
家計簿アプリの Django 設定。

秘密の情報や環境ごとに変わる値は、リポジトリに書かずに環境変数から読み込む（技術選定書 7.2 S-05）。
手元の開発では、リポジトリ直下の `.env` に書いておけば自動で読み込まれる（見本は `.env.example`）。
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# 環境変数の型と既定値。既定値は「安全側」にしておき、開発時だけ .env で緩める
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)
environ.Env.read_env(BASE_DIR / ".env")

# 本番では必ず環境変数で渡す。未設定なら起動時にエラーにして気づけるようにする
SECRET_KEY = env("SECRET_KEY")

# 本番で True にすると、エラー画面に設定値やコードが表示されてしまう
DEBUG = env("DEBUG")

ALLOWED_HOSTS = env("ALLOWED_HOSTS")


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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
