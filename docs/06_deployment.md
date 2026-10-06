# デプロイ設計書：家計簿アプリ（BudgetManager）

| 項目 | 内容 |
|---|---|
| 文書番号 | 06 |
| 版数 | 0.6 |
| 作成日 | 2026-10-06 |
| 作成者 | major182 |
| 前提となる文書 | [01 要件定義書](01_requirements.md)、[02 技術選定書](02_tech-stack.md) |

AWS 上でアプリを動かし、本人の端末から Tailscale を通してだけ使えるようにするための設計と、構築・運用の手順をまとめる。
構築（Terraform）と自動デプロイを作ったあと、各章の手順を実際の値で確かめて更新する。

---

## 目次

1. 構成と決定事項
2. 費用
3. 秘密情報と設定値
4. サーバーの中の構成
5. インフラ（Terraform）
6. アプリのデプロイ
7. 日々の運用
8. 後片付け
9. つまずきポイント早見表
10. 用語集
11. 改訂履歴

---

## 1. 構成と決定事項

### 1.1 決めたこと

| 項目 | 決定 | 理由 |
|---|---|---|
| 稼働方針 | **使うときだけ起動する**。作業を終えたら EC2 と RDS を止め、課題が終わったら全部削除する | 24時間動かすと月 約 $34 かかり、クレジットの期限（2027-03-27）までもたない（2章） |
| リージョン | ap-northeast-1（東京） | NF-EN-03 |
| アプリのサーバー | **EC2 t4g.micro（ARM）1台**、Amazon Linux 2023、ディスク 10GB | 技術選定書 8章。同じメモリ（1GB）の t3.micro より安い |
| データベース | **RDS for MySQL 8.4.11**、db.t4g.micro、20GB、シングル AZ | 技術選定書 4章。プライベートサブネットに置く（NF-SE-03） |
| 接続の制限 | **Tailscale**。EC2 のセキュリティグループは**受信をすべて拒否**する | NF-SE-01。Tailscale はサーバーから外へ接続して通信路を作るため、受け付ける口が要らない |
| HTTPS | `tailscale serve` が `https://budget.<tailnet>.ts.net` で受け、EC2 の中の Gunicorn（127.0.0.1:8000）へ渡す | NF-SE-02。証明書は Tailscale が自動で発行・更新する |
| 外への通信 | パブリックサブネットに置き、**自動で割り当てる公開 IP** を使う。Elastic IP は使わない | Tailscale・ECR・SSM への接続に外への経路が要る。NAT ゲートウェイ（月 約 $45）は高い。自動の IP は止めている間は課金されない |
| イメージ | GitHub Actions の ARM のランナーでビルドし、**Amazon ECR** に置く | t4g.micro（メモリ 1GB）の中ではビルドしない。前回と同じ作り |
| デプロイ | main へのマージで、GitHub Actions が **OIDC** で AWS に入り、**SSM** で EC2 の `deploy.sh` を実行する | 鍵を GitHub に置かない。SSH の口も要らない |
| サーバーの保守 | **SSM Session Manager** で入る | 鍵が要らず、権限を IAM で管理できる。Tailscale が止まっていても入れる（技術選定書 6.1 を変更） |
| 秘密情報 | **SSM パラメータストア**（SecureString） | NF-SE-04。Secrets Manager は1件あたり月 $0.40 かかるため使わない（3章） |
| バックアップ | RDS の自動バックアップ（1日）＋ **毎日 S3 に書き出し、7日で自動削除** | NF-AV-03。無料プランでは RDS の保存期間が最大1日のため、S3 で7日分を持つ（7.5） |
| ログ | Docker の awslogs で **CloudWatch Logs** に送り、**30日で自動削除** | NF-OP-01・02 |
| 定期処理 | EC2 の cron（日本時間） | 技術選定書 5章（4.3） |
| 構成の管理 | Terraform。状態ファイル（tfstate）は手元の PC に置き、リポジトリには入れない | NF-OP-03。1人で使うため、共有の置き場（S3）は作らない |
| 費用の見張り | AWS Budgets（月 $5）とコスト異常検出。**アカウントに設定済みのものを使い、Terraform では作らない** | 消し忘れ・使いすぎに気づく（2.4） |

### 1.2 構成図

```
   本人の PC・スマホ（Tailscale を起動）
                 │ HTTPS（https://budget.<tailnet>.ts.net）
                 │ Tailscale の暗号化された通信路
                 ▼
 ┌─ AWS 東京リージョン ──────────────────────────────────────────┐
 │ ┌─ VPC 10.0.0.0/16 ───────────────────────────────────────┐ │
 │ │ ┌─ パブリックサブネット（AZ-a）10.0.1.0/24 ────────────┐ │ │
 │ │ │ EC2 t4g.micro / Amazon Linux 2023                    │ │ │
 │ │ │  ├ tailscaled ＋ tailscale serve（HTTPS の入口）      │ │ │
 │ │ │  ├ app コンテナ（Gunicorn ＋ Django ＋ WhiteNoise）   │ │ │
 │ │ │  └ cron（定期収支・バックアップ・祝日）               │ │ │
 │ │ │ セキュリティグループ：受信なし／送信はすべて許可       │ │ │
 │ │ └───────────────────┬──────────────────────────────────┘ │ │
 │ │                     │ 3306番（EC2 の SG からだけ許可）     │ │
 │ │ ┌─ プライベートサブネット（AZ-a 10.0.11.0/24・AZ-c 10.0.12.0/24）┐ │
 │ │ │ RDS db.t4g.micro / MySQL 8.4.11                      │ │ │
 │ │ └──────────────────────────────────────────────────────┘ │ │
 │ └──────────────────────────────────────────────────────────┘ │
 │   ECR（イメージ）  S3（バックアップ・7日）  CloudWatch Logs（30日） │
 │   SSM（パラメータストア・Session Manager）                     │
 └──────────────────────────────────────────────────────────────┘
          ▲ OIDC ＋ SSM
   GitHub Actions（main へのマージでビルド・デプロイ）
```

- プライベートサブネットにはインターネットへの経路がない。RDS には EC2 を経由しないと届かない
- RDS は、使わなくても「2つの AZ にまたがるサブネットの組」を求めるため、AZ-c にもサブネットを作る（空のまま）

### 1.3 安全のための設計

| 対策 | 内容 | 要件 |
|---|---|---|
| 受け付ける口がない | EC2 のセキュリティグループに受信の規則を1つも書かない。インターネットから EC2 を見つけられない | NF-SE-01 |
| Tailscale のアクセス制御 | 本人の端末から、サーバー（`tag:server`）の 443番だけを許す。サーバーから本人の端末へは接続できない（3.2） | NF-SE-01 |
| Gunicorn は 127.0.0.1 だけで待つ | Tailscale を通らずにアプリへ届く経路を作らない | NF-SE-01 |
| DB はプライベートサブネット | RDS のセキュリティグループは、EC2 のセキュリティグループからの 3306番だけを許す | NF-SE-03 |
| 秘密情報はパラメータストア | リポジトリ・イメージ・Terraform のコードに秘密情報を書かない | NF-SE-04 |
| Django の本番の設定 | `DEBUG = False`、HTTPS 用の Cookie の設定など。CI で `manage.py check --deploy` を通す | S-05・S-07 |
| デプロイは main だけ | GitHub Actions の発火条件を main への push に限る。OIDC の信頼条件もリポジトリと main に限る（6.3） | NF-OP-04 |

---

## 2. 費用

金額は AWS の請求と同じ USD で書く。単価は 2026-10-06 に AWS の料金 API（`aws pricing get-products`）で確かめた東京リージョンの値。

### 2.1 クレジットと無料プランの制限

| 項目 | 内容 |
|---|---|
| クレジットの残高 | **$159.52**（2026-10-06、`aws freetier get-account-plan-state` で確認） |
| 有効期限 | **2027-03-27**。使い切るか期限が来ると、通常の請求に切り替わる |
| 無料プランの制限 | RDS の自動バックアップの保存期間は**最大1日**。EC2 は t4g.micro を使える |

### 2.2 単価

| 項目 | 単価 | 課金される条件 |
|---|---|---|
| EC2 t4g.micro | $0.0108／時 | 起動中のみ |
| RDS db.t4g.micro（MySQL、シングル AZ） | $0.025／時 | 起動中のみ（止めても7日で自動で起動する。7.3） |
| 公開 IPv4 アドレス | $0.005／時 | EC2 の起動中のみ（自動で割り当てる IP は、止めると手放す） |
| EBS（EC2 のディスク）gp3 10GB | $0.096／GB・月 → $0.96／月 | **存在する限り常に** |
| RDS のストレージ gp3 20GB | $0.138／GB・月 → $2.76／月 | **存在する限り常に** |
| ECR・S3・CloudWatch Logs | 合わせて月 $0.1 未満 | イメージ 約 200MB、バックアップ 7日分、ログ 30日分 |
| VPC・サブネット・セキュリティグループ・パラメータストア（標準） | $0 | ― |

### 2.3 見積もり

| 使い方 | 月額 |
|---|---|
| 止めている間（ディスクと保存領域だけ） | 約 $3.8 |
| 作業のときだけ起動（月 80 時間） | 約 $7.1（起動中 $0.0408 × 80 時間 ＋ $3.8） |
| 参考：24時間動かす | 約 $33.6 |
| 全部削除 | $0 |

作業のときだけ起動する使い方なら、期限（約 5.7 か月）まで使っても 約 $41 で、クレジットに十分収まる。
気をつけるのは金額よりも **「止め忘れ」と「RDS の自動の起動」**（7.3）。

### 2.4 請求の見張り

| 設定 | 内容 |
|---|---|
| 予算アラート（AWS Budgets） | 予算「free」：月 **$5**、実績が超えたらメールで知らせる。クレジットを費用に含める（既定）ため、クレジットが尽きて実際の請求が始まったときだけ鳴る |
| コスト異常検出 | 有効にする。普段と違う使われ方を知らせる |

どちらもアカウントを作ったときに設定済みだったため、そのまま使う（2026-10-06 に確認）。Terraform で作ると重複し、コスト異常検出はアカウントに1つしか作れないため。

---

## 3. 秘密情報と設定値

### 3.1 パラメータストア

パス `/budget/` の下に置く。EC2 は起動のたびに読み込み、アプリの環境変数のファイル（`/opt/budget/app.env`、所有者だけが読める）を作り直す。

| 名前 | 種類 | 中身 | 作る人 |
|---|---|---|---|
| `/budget/SECRET_KEY` | SecureString | Django の秘密の鍵（ランダム 50 文字） | Terraform（`random_password`） |
| `/budget/DATABASE_URL` | SecureString | `mysql://<ユーザー>:<パスワード>@<RDS の接続先>:3306/budget` | Terraform（パスワードは `random_password`） |
| `/budget/ALLOWED_HOSTS` | String | `budget.<tailnet>.ts.net` | Terraform（`tailnet_domain` の値から） |
| `/budget/TAILSCALE_AUTHKEY` | SecureString | Tailscale の認証キー | **利用者**（3.2。値を会話やリポジトリに書かない） |

- Terraform が作った秘密の値は、手元の状態ファイル（tfstate）にも平文で残る。tfstate はリポジトリに入れず（`.gitignore`）、手元の PC だけに置く
- 環境変数の名前は、開発と同じ（`.env.example`）。`DEBUG` は本番では設定せず、既定値の `False` を使う（S-05）
- `PRODUCTION=True` はイメージ（`Dockerfile`）に入れてある。HTTPS 用の Cookie・HSTS・HTTP から HTTPS への転送・静的ファイルのハッシュ付きの名前が有効になる（`config/settings.py`）

### 3.2 Tailscale の準備（利用者の作業）

1. Tailscale のアカウントを作り、PC とスマホにアプリを入れて、同じアカウントでログインする
2. 管理画面の Access controls に、次の規則を書く（本人の端末からサーバーの 443番だけを許す）

   ```json
   {
     "tagOwners": { "tag:server": ["autogroup:admin"] },
     "grants": [
       { "src": ["autogroup:member"], "dst": ["tag:server"], "ip": ["443"] }
     ]
   }
   ```

3. 管理画面の DNS で、MagicDNS と HTTPS Certificates を有効にする。表示される tailnet の名前（`xxxx.ts.net`）を `terraform.tfvars` の `tailnet_domain` に書く
4. Settings → Keys で、認証キーを発行する。**使い捨て（Reusable を外す）・Pre-approved・タグ `tag:server`**。表示された値を、手元の PowerShell から登録する

   ```powershell
   aws ssm put-parameter --name /budget/TAILSCALE_AUTHKEY --type SecureString --value "<表示されたキー>" --overwrite
   ```

- タグ付きの端末は、鍵の有効期限が切れない。EC2 を止めて起動し直しても、そのまま参加し続ける
- EC2 を作り直したとき（削除して作り直す、`user_data.sh` を変えた）は、新しい認証キーを発行し直す

---

## 4. サーバーの中の構成

### 4.1 初期設定（`user_data.sh`、EC2 を作ったときに1回だけ動く）

1. タイムゾーンを `Asia/Tokyo` にする（cron を日本時間で動かすため）
2. スワップ（1GB）を作る（メモリ 1GB での起動時の不足を防ぐ）
3. Docker・cronie を入れて有効にする（Amazon Linux 2023 のパッケージ。2026-10-06 の構築では Docker 25.0.16）
4. Tailscale を入れ、パラメータストアの認証キーで参加する（`tailscale up --authkey=… --hostname=budget`）。キーを扱う間はコマンドの記録（`set -x`）を止め、キーがログや EC2 のコンソールの出力に残らないようにする
5. `tailscale serve --bg --https=443 http://127.0.0.1:8000` で HTTPS の入口を作る（設定は残り、再起動後も続く）
6. 次のスクリプトと、systemd・cron の設定を置く（スクリプトは `/opt/budget/`）

| ファイル | 役割 |
|---|---|
| `load-env.sh` | パラメータストアから `/budget/` を読み、`app.env` を作る |
| `deploy.sh` | ECR にログイン → イメージを取得 → コンテナを入れ替え → 死活確認 → 古いイメージの掃除（6.2） |
| `run-task.sh` | アプリのコンテナの中で管理コマンドを動かし、出力をコンテナのログ（→ CloudWatch Logs）に送る |
| `backup.sh` | `mysqldump` で書き出して圧縮し、S3 に置く（7.5） |
| `restore.sh` | S3 のバックアップから DB を戻す。戻す間はアプリを止める（7.5） |
| `/etc/systemd/system/budget.service` | 起動時に `load-env.sh` → `deploy.sh` を動かす |
| `/etc/cron.d/budget` | 定期処理（4.3） |

### 4.2 アプリのコンテナ

| 項目 | 内容 |
|---|---|
| 起動 | `docker run -d --name app --restart unless-stopped -p 127.0.0.1:8000:8000 --env-file /opt/budget/app.env --log-driver awslogs …` |
| イメージ | `Dockerfile`。`python:3.14.7-slim-trixie` を土台に、依存を uv で入れ、`collectstatic` まで済ませる。管理者でない利用者（uid 10001）で動かす。大きさ 約 250MB |
| 起動時の処理 | `docker/app/entrypoint.sh`：`migrate` → Gunicorn（`docker/app/gunicorn.conf.py`、ワーカー 2）。引数を付けると、その管理コマンドを動かす |
| 静的ファイル | WhiteNoise が配信（本番だけ。開発では開発用サーバーが配信する）。ファイル名にハッシュを付け、圧縮し、ブラウザに長く保存させる。同梱の Chart.js に残る `.map` への参照で失敗しないよう、JavaScript の中の参照は書き換えない（`core/storage.py`） |
| HTTPS の判定 | `tailscale serve` が付ける `X-Forwarded-Proto: https` で判定する（Tailscale 1.102.5 のソースで確認）。Gunicorn には 127.0.0.1 からしか届かないため、この見出しを偽れない |
| ログ | 標準出力に出し、awslogs で CloudWatch Logs のロググループ `/budget/app` に送る（30日で削除） |
| メモリ | Gunicorn のワーカー 2 で 約 200MB。t4g.micro（1GB）に収まる |

### 4.3 定期処理（cron、日本時間）

| 時刻 | 処理 | 要件 |
|---|---|---|
| 毎日 0:05 | `register_recurring`（定期収支の自動登録） | BT-01 |
| 毎日 0:30 | `backup.sh`（DB の書き出し） | NF-AV-03 |
| 1月1日・12月1日の 1:00 | `import_holidays`（祝日データの更新） | BT-02 |
| 起動の 3 分後 | `register_recurring` | 止めていた日の分を登録する |

- 使うときだけ起動するため、0:05 に EC2 が止まっていることが多い。**起動時にも `register_recurring` を動かし、止めていた日の分をまとめて登録する**（BT-01 のさかのぼり登録。DB 設計書 5.8）
- 結果（登録件数・失敗）は管理コマンドがログに出し、CloudWatch Logs に残る（NF-OP-02）

---

## 5. インフラ（Terraform）

### 5.1 ファイル構成

```
infra/terraform/
├── versions.tf               Terraform と AWS プロバイダーの版
├── variables.tf              変数（tailnet_domain、db_deletion_protection など）
├── terraform.tfvars.example  変数の見本（本物の terraform.tfvars はリポジトリに入れない）
├── network.tf                VPC・サブネット・ルート・セキュリティグループ
├── ec2.tf                    EC2・IAM ロール（SSM・ECR・S3・CloudWatch Logs・パラメータストアの読み取り）
├── rds.tf                    RDS・サブネットグループ
├── ecr.tf                    ECR（古いイメージは5つを残して削除）
├── backup.tf                 S3（公開を禁止・暗号化・7日で削除）
├── ssm.tf                    パラメータストアの値（TAILSCALE_AUTHKEY 以外）
├── logs.tf                   CloudWatch Logs（30日）
├── github_oidc.tf            GitHub Actions 用の OIDC と IAM ロール
├── user_data.sh              EC2 の初期設定（4.1）
└── outputs.tf                インスタンス ID・URL など
```

### 5.2 利用者が設定する値（`terraform.tfvars`）

| 変数 | 内容 | 例 |
|---|---|---|
| `tailnet_domain` | Tailscale の tailnet の名前 | `tail1234.ts.net` |
| `db_deletion_protection` | RDS の削除の保護。課題の期間中は `true` | `true` |

### 5.3 構築する

EC2 は起動時に ECR のイメージを取り込むため、**ECR を先に作り、イメージを置いてから残りを作る**。

```powershell
terraform -chdir=infra/terraform init
# 1. ECR だけを作る
terraform -chdir=infra/terraform apply -target=aws_ecr_repository.app -target=aws_ecr_lifecycle_policy.app
# 2. 手元で ARM のイメージを作って置く（自動デプロイ（6章）ができたあとは、main へのマージでもよい）
$repo = terraform -chdir=infra/terraform output -raw ecr_repository_url
aws ecr get-login-password | docker login --username AWS --password-stdin $repo.Split("/")[0]
docker buildx build --platform linux/arm64 --provenance=false --sbom=false -t "$($repo):latest" --push .
# 3. 残りを作る（RDS の作成に 約 9 分）
terraform -chdir=infra/terraform plan
terraform -chdir=infra/terraform apply
# 4. 新しい DB に祝日データを入れる（EC2 の起動から 約 3 分後）
aws ssm send-command --instance-ids (terraform -chdir=infra/terraform output -raw instance_id) --document-name AWS-RunShellScript --parameters 'commands=["/opt/budget/run-task.sh import_holidays"]'
```

### 5.4 構築後に確かめること

| 確かめること | 方法 |
|---|---|
| EC2 の受信の規則が空 | `aws ec2 describe-security-groups` で `IpPermissions` が空 |
| サーバーが Tailscale に参加した | Tailscale の管理画面に `budget`（`tag:server`）が出る |
| アプリが開く | PC とスマホで Tailscale を起動し、`https://budget.<tailnet>.ts.net` を開く |
| Tailscale を切ると開けない | Tailscale を切って同じ URL を開き、つながらないことを確かめる（受け入れ基準 4） |
| ログが届く | CloudWatch Logs の `/budget/app` に Gunicorn の起動のログがある |
| 公開 IP に直接つないでも応答しない | EC2 の公開 IP に `curl http://<IP>/` などでつなぎ、応答がないことを確かめる |
| バックアップが置ける | サーバーの中で `sudo /opt/budget/backup.sh` を動かし、S3 にファイルができる |

---

## 6. アプリのデプロイ

### 6.1 自動デプロイの流れ

```
 main にマージ ─▶ CI（ci.yml）が成功 ─▶ GitHub Actions（.github/workflows/deploy.yml）
                   0. アプリに関わる変更がなければ、ここで終わる
                   1. ARM のランナーでイメージをビルド
                   2. ECR に push（latest と コミット ID の2つのタグ）
                   3. タグ Project=budget の起動中の EC2 を探す（1台に定まらなければ止める）
                   4. SSM で EC2 の /opt/budget/deploy.sh を実行
                   5. 死活確認が通らなければワークフローを失敗させる
```

| 決めたこと | 理由 |
|---|---|
| `docs/`・`infra/`・`prototype/`・`*.md` だけの変更ではデプロイしない | 設計書だけの変更で無駄にデプロイしない。Terraform の変更は手で `apply` する |
| 発火条件は「main への `push` で動いた CI の成功」（`workflow_run`）。`pull_request` では動かさない | CI が通ったコミットだけをデプロイする（NF-OP-04）。公開リポジトリでは、他人の PR のコードが AWS の権限付きで動いてしまうため |
| デプロイは同時に1つだけ（`concurrency`） | 続けてマージしても、入れ替えがぶつからない |
| 完了は 5 秒ごとに確かめ、最大 10 分待つ | `aws ssm wait` は 100 秒で打ち切られ、時間のかかるデプロイを失敗と誤るため使わない |
| デプロイ先はタグで探す | EC2 を作り直すとインスタンス ID が変わるため |
| **EC2 が止まっていると、デプロイは失敗する** | 起動してから、GitHub の Actions の画面で再実行する。起動時にも `deploy.sh` が最新のイメージを取り込む |

### 6.2 `deploy.sh` の手順

1. ECR にログインし、`latest`（引数があればそのタグ）のイメージを取得する
2. 動いているコンテナを止めて消し、新しいイメージで起動する（4.2）
3. `http://127.0.0.1:8000/` が応答するまで最大 60 秒待つ。応答しなければ失敗として終わる
4. 動いている版以外のアプリのイメージを消す（ディスク 10GB を圧迫しないため）。前の版に戻すときは ECR から取り出し直す（ECR には5つ残る）

前の版に戻すときは、コミット ID のタグを指定して実行する（`sudo /opt/budget/deploy.sh <コミット ID>`）。

### 6.3 OIDC の注意

GitHub が AWS に送る識別子は、名前だけでなく**数値 ID を含む形式**になる（前回の課題で確認）。

```
実際に届く形: repo:major182@<オーナー ID>/BudgetManager@<リポジトリ ID>:ref:refs/heads/main
```

ID は `gh api repos/major182/BudgetManager --jq '.owner.id, .id'` で調べ、`github_oidc.tf` の信頼条件に使う。
ロールの ARN は GitHub の Secret `AWS_ROLE_ARN` に登録する。

---

## 7. 日々の運用

### 7.1 よく使うコマンド

```powershell
terraform -chdir=infra/terraform output    # インスタンス ID・URL
# サーバーに入る
aws ssm start-session --target (terraform -chdir=infra/terraform output -raw instance_id)
# 今月の請求額とクレジットの残高
aws ce get-cost-and-usage --time-period Start=<月初>,End=<今日> --granularity MONTHLY --metrics UnblendedCost --output table
aws freetier get-account-plan-state --region us-east-1
```

サーバーの中で：

```bash
sudo docker ps                                    # コンテナの状態
sudo /opt/budget/run-task.sh register_recurring   # 定期収支の登録を手で動かす
sudo tailscale status                             # Tailscale の状態
```

### 7.2 使い始める（起動する）

```powershell
# RDS を先に起動する（EC2 が先だと、アプリが DB につながらず再起動を繰り返す）
aws rds start-db-instance --db-instance-identifier budget-db
aws rds wait db-instance-available --db-instance-identifier budget-db
aws ec2 start-instances --instance-ids (terraform -chdir=infra/terraform output -raw instance_id)
```

起動から 約 3 分で、`https://budget.<tailnet>.ts.net` が開けるようになる。止めていた日の定期収支も登録される（4.3）。

### 7.3 使い終わる（止める）

```powershell
aws ec2 stop-instances --instance-ids (terraform -chdir=infra/terraform output -raw instance_id)
aws rds stop-db-instance --db-instance-identifier budget-db
```

| 混同しやすいこと | 内容 |
|---|---|
| データ | 止めても消えない。消えるのは削除（8章）したときだけ |
| RDS を止めていられる期間 | **最大7日**。過ぎると AWS が自動で起動し、課金が再開する。1週間以上使わないときは、もう一度止めるか、8章で削除する |
| 止めている間のバックアップ | 取られない（データも変わらない） |

### 7.4 運用のパターン

| パターン | 操作 | 月額 | データ | 使う場面 |
|---|---|---|---|---|
| ① 起動したまま | 何もしない | 約 $34 | 残る | 提出の確認・発表の直前だけ |
| ② 止める | 7.3 | 約 $3.8 ＋ 使った分 | 残る | その日の作業を終えるとき |
| ③ 全部削除 | 8章 | $0 | 消える（先に書き出す） | 課題が終わったとき |

### 7.5 バックアップと戻し方

| 種類 | 時刻 | 保存期間 | 戻せる範囲 |
|---|---|---|---|
| RDS の自動バックアップ | 毎日 3:00〜4:00（起動中のみ） | 1日 | 直近1日の任意の時点 |
| S3 への書き出し（`backup.sh`） | 毎日 0:30（起動中のみ）。手でも動かせる | **7日**（S3 の規則で自動削除） | 7日分の各日の 0:30 の時点 |

S3 から戻す手順（サーバーの中で）：

```bash
aws s3 ls s3://<バックアップのバケット>/                       # 日付ごとのファイルを確かめる
sudo /opt/budget/restore.sh <ファイル名>                        # アプリを止め、DB を戻し、アプリを起動し直す
```

- 削除（8章）すると、RDS の自動バックアップも S3 のバックアップも消える。**残したいときは、先に S3 のファイルを手元に保存する**
- 戻す練習を、受け入れの確認（D5）で一度行う

### 7.6 Tailscale の端末の管理

| こと | 操作 |
|---|---|
| 端末を足す | その端末に Tailscale を入れ、同じアカウントでログインする |
| 端末を失くした | Tailscale の管理画面の Machines で、その端末を Remove する。以後その端末からはつながらない |
| サーバーの名前が `budget-1` などになった | 古いサーバーが管理画面に残っている。古いほうを Remove し、新しいほうの名前を `budget` に変える |

---

## 8. 後片付け（課題が終わったら必ず実行する）

1. 残したいデータがあれば、S3 のバックアップを手元に保存する（`aws s3 cp s3://<バックアップのバケット>/<ファイル名> .`）
2. `terraform.tfvars` の `db_deletion_protection` を `false` にして `apply` する
3. 削除する

```powershell
terraform -chdir=infra/terraform destroy
```

4. 消し残しがないか確かめる（残っていると課金が続く）

```powershell
aws ec2 describe-instances --query "Reservations[].Instances[?State.Name!='terminated'].[InstanceId,State.Name]" --output table
aws ec2 describe-volumes --output table
aws rds describe-db-instances --query "DBInstances[].DBInstanceIdentifier"
aws rds describe-db-snapshots --query "DBSnapshots[].DBSnapshotIdentifier"
aws ecr describe-repositories --output table
aws s3 ls
```

5. Tailscale の管理画面で、サーバー（`budget`）を Remove する

**作り直すとき**は、5.3 の手順で構築したあと、手元に保存したバックアップを新しいバケットに置いて戻す（`aws s3 cp <ファイル名> s3://<バックアップのバケット>/` → サーバーの中で `sudo /opt/budget/restore.sh <ファイル名>`）。Tailscale の認証キーは使い捨てのため、新しく発行して登録しておく（3.2）。2026-10-06 に、削除から戻すまでを 約 16 分で行えることを確かめた
6. 数日後に、請求の画面で費用が増えていないことを確かめる

---

## 9. つまずきポイント早見表

| 症状 | 原因 | 対処 |
|---|---|---|
| ブラウザで開けない | その端末で Tailscale が起動していない | Tailscale を起動する（最も多い） |
| ブラウザで開けない（Tailscale は起動している） | EC2・RDS が止まっている、起動の途中 | 7.2。起動から 3 分ほど待つ |
| `Bad Request (400)` と表示される | `ALLOWED_HOSTS` と開いた URL の名前が違う | `budget.<tailnet>.ts.net` で開く。サーバーの名前が変わったら 7.6 |
| アプリが DB につながらない | RDS が止まっている・起動の途中 | RDS が `available` か確かめる。起動は RDS が先（7.2） |
| サーバーが Tailscale に出てこない | 認証キーの期限切れ・使用済み | 新しい認証キーを発行して登録し（3.2）、EC2 を作り直すか、サーバーの中で `tailscale up` をやり直す |
| 自動デプロイが「デプロイ先が1台に定まりません」で失敗 | EC2 が止まっている | EC2 を起動して、ワークフローを再実行する |
| 自動デプロイが OIDC の認証で失敗 | 信頼条件の識別子が合っていない | 6.3 |
| `FreeTierRestrictionError` | 無料プランの制限（2.1） | 値を制限の中にする（バックアップの保存期間は 1日まで） |
| アプリが再起動を繰り返す・`app.env` に `DATABASE_URL` がない | EC2 が、DB の接続先をパラメータストアに入れる前に起動した | `sudo systemctl restart budget`（設定を読み直して起動する）。Terraform では EC2 をパラメータの後に作るようにしてある |
| `plan` に `-/+`（作り直し）が出た | `user_data.sh` の変更など。EC2 を作り直すとサーバーの状態が消える | apply の前に内容を確かめる。EC2 なら認証キーを用意してから（3.2） |
| SSM で接続できない | エージェントの登録待ち | 3 分待つ。`aws ssm describe-instance-information` で確かめる |
| 手元の PC から DB につなげない | 設計どおり（RDS は外から届かない） | EC2 の中から操作する |
| `destroy` で RDS が消せない | 削除の保護が有効 | 8章の手順 2 |
| 削除したのに課金される | RDS のスナップショット・EBS が残っている | 8章の手順 4 で探して消す |
| イメージを作るときに `failed to connect to the docker API` | 手元の Docker Desktop が起動していない | Docker Desktop を起動してから、もう一度実行する |
| コンソールに何も出ない | 見ているリージョンが違う | 画面の右上で「東京」を選ぶ |

---

## 10. 用語集

| 用語 | 意味 |
|---|---|
| Tailscale | 自分の端末どうしだけをつなぐ VPN のサービス。参加した端末どうしは暗号化された通信路でつながる |
| tailnet | Tailscale で自分の端末が参加するネットワーク。`xxxx.ts.net` の名前を持つ |
| MagicDNS | tailnet の中の端末に `budget.xxxx.ts.net` のような名前を付ける Tailscale の機能 |
| `tailscale serve` | tailnet の中だけに HTTPS でアプリを公開する Tailscale の機能。証明書も自動で用意する |
| 認証キー | サーバーのように画面でログインできない端末を、tailnet に参加させるための鍵 |
| VPC／サブネット | 自分専用の仮想のネットワーク／それを区切った小部屋 |
| パブリック／プライベートサブネット | インターネットへの経路を持つ／持たないサブネット |
| セキュリティグループ | 仮想のファイアウォール。書いた通信だけを通す |
| EC2／EBS | 仮想サーバー／そのディスク |
| RDS | AWS が運用するデータベース。バックアップや更新を代わりに行う |
| ECR | コンテナのイメージの保管庫 |
| S3 | ファイルの保管庫。保存期間の規則（ライフサイクル）で古いファイルを自動で消せる |
| CloudWatch Logs | ログの保管庫。保存期間を決めて自動で消せる |
| SSM（Systems Manager） | サーバーの管理の機能の集まり。Session Manager（鍵なしでサーバーに入る）とパラメータストア（設定値・秘密情報の保管）を使う |
| IAM ロール | サービスに持たせる権限の束 |
| OIDC | 外部のサービスと信頼関係を結ぶ認証の方式。鍵を保存しなくてよい |
| user_data | EC2 を作ったときに1回だけ動くスクリプト |
| tfstate | Terraform が「何を作ったか」を記録するファイル。なくすと管理できなくなる |

---

## 11. 改訂履歴

| 版数 | 日付 | 内容 |
|---|---|---|
| 0.1 | 2026-10-06 | 作成（デプロイの設計。構築・自動デプロイの前） |
| 0.2 | 2026-10-06 | 本番の設定とイメージ（3.1・4.2）を、作ったものに合わせて追記 |
| 0.6 | 2026-10-06 | 品質チェックの結果を反映：認証キーをログに残さない（4.1）、古いイメージの片付け（6.2）、自動デプロイの完了待ち（6.1）、systemd・cron の設定の置き場所（4.1）、WhiteNoise を本番だけで使う（4.2） |
| 0.5 | 2026-10-06 | 削除と作り直しの確認の結果を反映（8章の手順・つまずきポイント） |
| 0.4 | 2026-10-06 | 自動デプロイ（6.1）を、作ったワークフローに合わせて更新 |
| 0.3 | 2026-10-06 | 構築の結果に合わせて更新：予算のアラートは設定済みのものを使う（1.1・2.4）、構築の手順（5.3）、確かめること（5.4）、Docker の版数（4.1）、つまずきポイント |
