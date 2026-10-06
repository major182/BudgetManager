# 家計簿アプリ（BudgetManager）

スクール課題として作成する家計簿アプリです。

- 開発の進め方・規約：[CLAUDE.md](CLAUDE.md)
- 要件定義書：[docs/01_requirements.md](docs/01_requirements.md)
- 技術選定書：[docs/02_tech-stack.md](docs/02_tech-stack.md)
- DB 設計書：[docs/03_db-design.md](docs/03_db-design.md)
- 画面設計書：[docs/04_screen-design.md](docs/04_screen-design.md)
- テスト仕様書：[docs/05_test-spec.md](docs/05_test-spec.md)
- デプロイ設計書（AWS の構築・運用の手順）：[docs/06_deployment.md](docs/06_deployment.md)

## 開発の始め方（Windows）

前提：[uv](https://docs.astral.sh/uv/) 0.12.21 と Docker Desktop が入っていること。

```powershell
# 1. Python 3.14.7 と、使うライブラリを入れる（バージョンは uv.lock で固定）
uv sync

# 2. 環境変数のファイルを作り、SECRET_KEY を書き換える（手順は .env.example の中）
Copy-Item .env.example .env

# 3. 開発用の MySQL 8.4.11 を起動する
docker compose up -d

# 4. DB にテーブルを作る
uv run python manage.py migrate

# 5. 祝日データを取り込む（営業日の計算と、カレンダーの祝日の表示に使う）
uv run python manage.py import_holidays

# 6. 開発用サーバーを起動する → http://127.0.0.1:8000/
uv run python manage.py runserver
```

## チェック

lint・整形・型・テストをまとめて実行します（CI でも同じものが動きます）。

```powershell
uv run python scripts/check.py
```
