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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# データベース
# 段階3で MySQL に切り替えるまでの仮の設定
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# 言語・タイムゾーン
# 日付は日本時間で扱う（要件定義書 BR-04）
LANGUAGE_CODE = "ja"

TIME_ZONE = "Asia/Tokyo"

USE_I18N = True

USE_TZ = True


# CSS・JavaScript・画像
STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
