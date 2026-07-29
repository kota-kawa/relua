# JOB HARBOR — All Job MVP

インターン・本選考情報を、ログインなしで検索できる公開型の就活情報サービスです。募集情報の追加・更新は運営者本人の認証済みMCP接続に限定し、固定値マスタ、厳格な入力検証、冪等性、監査ログによってデータ品質を保ちます。

このリポジトリは [`要件定義書_v2.md`](./要件定義書_v2.md) の **v0.1（MVP）** と、19章のローカル保存・端末間共有機能を実装しています。ユーザーアカウントやサーバー側ブックマークは設けていません。

## 実装範囲

- Next.js 16 / React 19 / TypeScript / Tailwind CSS 4
  - 未ログインの一覧、キーワード検索、複合絞り込み、並び替え、ページング、詳細
  - Server ComponentsによるSSR、共有可能なURL、SEOメタデータ
  - ブラウザ内ブックマーク、最近見た募集、URL・QRコードによる端末間移行と共有リスト
  - デバイスの既定カレンダーへ渡すICS生成、JSON・CSVバックアップとインポート
  - デスクトップ・タブレット・モバイル対応
- FastAPI / SQLAlchemy / PostgreSQL
  - Next.jsからのみ利用する非公開REST API
  - マスタ参照、日付・URL・自由記述の検証、DB制約
  - 企業名・タグの正規化と再利用
- 公式MCP Python SDK（Streamable HTTP）
  - `search_opportunity`
  - `get_master_values`
  - `add_opportunity`
  - `update_opportunity`
  - Bearerトークン認証、Redisレート制限、request IDによる冪等化、成功・失敗監査ログ
- Alembic初期マイグレーション、固定値マスタ投入
- 締め切り超過を「締切」に更新する運用ジョブ
- Docker Compose、GitHub Actions、バックエンド自動テスト

依存ライブラリは実装時点の最新安定版を固定しています。TypeScriptとESLintだけは、Next.js 16.2.12が実際にビルド・lintできる最新互換版（TypeScript 6.0.3 / ESLint 9.39.5）です。TypeScript 7とESLint 10は現行Next.jsの利用するAPIに未対応のため採用していません。

## 起動

必要なものは Docker と Docker Compose だけです。

```bash
cp .env.example .env
docker compose up --build
```

- Web: <http://localhost:3100>
- 運営者用MCP（ローカルホスト限定）: `http://localhost:8000/mcp/`

PostgreSQLとRedisはホストへポートを公開しません。FastAPIも`127.0.0.1`だけにバインドされ、REST APIは内部トークン、MCPは運営者用Bearerトークンがなければ利用できません。

初回起動時にAlembicが固定値マスタまで投入します。本番用の募集情報は空の状態です。

### UI確認用デモデータ

```bash
docker compose exec api python -m app.scripts.seed_demo
```

投入される企業・募集はすべて架空です。実在情報と混同しないよう、本番環境では実行しないでください。同じコマンドを再実行してもrequest IDにより重複しません。

## MCPクライアント設定

ローカルで接続する場合、MCPクライアントに次のURLとヘッダーをStreamable HTTPサーバーとして登録します。

```text
http://localhost:8000/mcp/
```

```text
Authorization: Bearer <MCP_API_TOKENの値>
```

APIポートはループバック限定のため、別端末やインターネットからは直接接続できません。リモートサーバー上で運用する場合は、SSHポートフォワードまたは運営者専用VPNを通して接続してください。MCPを一般公開するリバースプロキシ設定は行わないでください。

推奨操作順は次のとおりです。

1. `get_master_values` で選択可能な固定値を取得する
2. `search_opportunity` で既存企業・募集を確認する
3. `add_opportunity` または `update_opportunity` を呼ぶ
4. 検証エラーでは、返された項目をすべて修正し、同じ `request_id` で再試行する

`add_opportunity` と `update_opportunity` の `payload` では、日付を `YYYY-MM-DD`、URLを `https` で指定します。更新は部分更新ではなく全項目置換です。

## 内部REST API

REST APIは公開せず、Next.jsサーバーと運用コマンドだけが`X-Internal-API-Token`ヘッダーを付けて利用します。ブラウザはAll Job APIへ直接接続せず、必要な公開情報だけをNext.jsの同一オリジン経由で取得します。

```text
GET /api/v1/health
GET /api/v1/masters
GET /api/v1/opportunities
GET /api/v1/opportunities/{id}
```

一覧では `q`、`status`、`industry`、`sector`、`event_type`、`event_format`、`job_category`、`graduation_year`、`degree`、`sort`、`page`、`per_page` を利用できます。複数選択する条件は同じクエリ名を繰り返します。

## ローカル保存と共有

募集カードまたは詳細画面の「保存」から、募集情報IDだけをブラウザの `localStorage` に保存します。保存・解除時にIDをサーバーへ送信せず、個人識別情報とも紐付けません。

- `/saved`: ブックマーク、最近見た募集、QR移行、共有URL、JSON・CSVバックアップ
- `/import#b=...`: 別端末の保存データを確認後にマージ
- `/list#jobs=...`: ログイン不要の共有リスト

QRコードはブラウザ内で生成します。URLフラグメントはサーバーへ送信されず、インポート時は存在する募集IDだけを既存データへ追加します。

これはリアルタイム同期ではなく、その時点の保存内容を別端末へマージする「引き継ぎ」です。引き継ぎ前には新規・保存済み・終了済みの件数と追加対象を確認できます。URLやQRコードの安定動作範囲を超える場合は、JSONバックアップを利用します。

## 運用

締切日を過ぎた募集の状態を更新します。cronやコンテナ基盤のスケジューラーから1日1回実行してください。

```bash
docker compose exec api python -m app.scripts.close_expired
```

監査記録は `audit_logs`、冪等性レコードは `idempotency_records` に保存されます。MVPでは監査ログ閲覧画面と自動ロールバックを実装していません。

## 開発時の検証

```bash
cd backend
pip install -r requirements-dev.txt
DATABASE_URL=sqlite:// pytest
ruff check .

cd ../frontend
npm ci
npm run lint
npm run build
```

Dockerを含む一括起動は `make up`、ログ確認は `make logs`、停止は `make down` です。

## 本番公開前の設定

- `.env` のDBパスワードを本番固有値へ変更する
- `API_INTERNAL_TOKEN`と`MCP_API_TOKEN`に、それぞれ異なる十分に長いランダム値を設定する
- `ENVIRONMENT=production`を設定する（開発用トークンのままではAPIが起動しない）
- PostgreSQL、Redis、FastAPIの公開ポートを追加しない
- FastAPIとNext.jsの前段でTLS、CDN、リクエストサイズ制限を設定する
- MCP接続にはSSHポートフォワードまたは運営者専用VPNを使用する
- 実在企業10社分をChatGPT・Claudeの両方から登録し、要件定義書17.4の受入試験を行う
