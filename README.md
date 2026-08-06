# relua

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
  - 検索・取得・固定値参照・重複確認の読み取りツール（認証不要）
  - 追加・全項目更新・状況更新・事前検証・書き込み履歴のツール（認証必要）
  - ツールごとの `title` / `annotations` / `outputSchema` と、各募集の詳細ページURL
  - Bearerトークン認証、Redisレート制限、request IDによる冪等化、同名イベントの重複検出、成功・失敗監査ログ
  - ChatGPT・Claudeから接続するためのOAuth 2.1認可サーバー（動的クライアント登録、PKCE、リフレッシュトークン）
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
- 運営者用MCP（ローカルホスト限定）: `http://localhost:8000/mcp`

PostgreSQLとRedisはホストへポートを公開しません。FastAPIも`127.0.0.1`だけにバインドされ、REST APIは内部トークン、MCPは運営者用Bearerトークンがなければ利用できません。

初回起動時にAlembicが固定値マスタまで投入します。本番用の募集情報は空の状態です。

### UI確認用デモデータ

```bash
docker compose exec api python -m app.scripts.seed_demo
```

投入される企業・募集はすべて架空です。実在情報と混同しないよう、本番環境では実行しないでください。同じコマンドを再実行してもrequest IDにより重複しません。

## MCPクライアント設定

接続方法は2通りあります。手元の端末から使うだけなら固定トークン、ChatGPTやClaudeのWeb版から使うならOAuthです。

### 固定トークン接続（既定）

MCPクライアントに次のURLとヘッダーをStreamable HTTPサーバーとして登録します。

```text
http://localhost:8000/mcp
```

```text
Authorization: Bearer <MCP_API_TOKENの値>
```

既定ではAPIポートがループバック限定のため、別端末やインターネットからは直接接続できません。リモートサーバー上で運用する場合は、SSHポートフォワードまたは運営者専用VPNを通して接続してください。

### OAuth接続（ChatGPT・Claude）

ChatGPTやClaudeのWeb版は任意のヘッダーを設定できないため、固定トークンでは接続できません。代わりに、MCPのURLだけを登録し、ブラウザでreluaのログイン画面に遷移してパスワードを入力する方式を用意しています。

有効化するには `.env` に次を設定します。

```bash
MCP_OAUTH_ENABLED=true
MCP_PUBLIC_URL=https://<公開ホスト名>
MCP_OPERATOR_PASSWORD=<12文字以上の固有パスワード>
```

クライアントには次のURLだけを登録します。認証情報の入力欄は空のままにしてください。

```text
https://<公開ホスト名>/mcp
```

接続時の流れは次のとおりです。

1. クライアントが認証なしでMCPを初期化し、ツール一覧と各ツールの認証要否を取得する
2. 読み取り系ツール（`search_opportunity`、`get_opportunity`、`get_master_values`、`get_sectors`、`find_similar_opportunities`）はそのまま利用できる
3. 書き込み系ツールを呼ぶと、401の `WWW-Authenticate` を受けてOAuthフローを開始する
4. `/.well-known/oauth-protected-resource/mcp` と `/.well-known/oauth-authorization-server` を読み、`/oauth/register` に自分自身を登録する
5. ブラウザが `/oauth/authorize` へ遷移し、reluaの接続許可画面が開く
6. `MCP_OPERATOR_PASSWORD` を入力すると、クライアントが `/oauth/token` でアクセストークンとリフレッシュトークンを受け取る

リフレッシュトークンは既定で無期限（`MCP_REFRESH_TOKEN_TTL_DAYS=0`）です。アクセストークンは1時間で切れますが、クライアントがリフレッシュトークンで自動更新するため、**一度接続すれば再ログインは不要**です。使うたびにトークンは入れ替わり、古いトークンが再利用された場合はその接続全体を失効させます。

この方式ではMCPエンドポイントをインターネットへ公開します。公開する場合は、前段にTLS終端のリバースプロキシを置き、`FORWARDED_ALLOW_IPS` にそのプロキシのIPを設定してください。ログイン試行回数の集計に接続元IPを使うため、この設定がないと回数制限が全体で1つになります。

登録自体は誰でも行えますが、登録しただけでは何も取得できません。トークンを発行できるのは運営者パスワードを入力したときだけです。

## MCPツール

| ツール | 認証 | 用途 |
| --- | --- | --- |
| `search_opportunity` | 不要 | キーワードと固定値で検索し、概要の一覧を返す |
| `get_opportunity` | 不要 | IDまたは公開コードで1件を全項目取得する |
| `get_master_values` | 不要 | 選択可能な固定値マスタを全件返す |
| `get_sectors` | 不要 | 指定した業界に属する業種だけを返す |
| `find_similar_opportunities` | 不要 | 同じ企業の登録済み募集を探し、二重登録を防ぐ |
| `validate_opportunity` | 必要 | 保存せずに検証し、固定値の誤りと重複の疑いを返す |
| `add_opportunity` | 必要 | 募集情報を1件追加する |
| `update_opportunity` | 必要 | 既存の募集情報を全項目置換で更新する |
| `update_recruitment_status` | 必要 | 募集状況と締め切りだけを更新する |
| `list_recent_writes` | 必要 | 直近の登録・更新の記録を返す |

各ツールは `title`、`annotations`（`readOnlyHint` など）、`outputSchema` を公開します。読み取り専用かどうかがクライアント側で判別できるため、ChatGPTやClaudeは読み取りツールの自動承認を判断できます。

すべての募集情報には詳細ページのURL（`url`）が含まれます。組み立てには `NEXT_PUBLIC_SITE_URL`（APIコンテナには `SITE_URL`）を使うため、公開環境では実際のサイトURLを設定してください。

推奨操作順は次のとおりです。

1. `get_master_values` で選択可能な固定値を取得し、業種は `get_sectors` で業界配下に絞る
2. `find_similar_opportunities` で同じ募集が登録済みでないか確認する
3. 内容に自信がない場合は `validate_opportunity` で先に検証する
4. `add_opportunity` または `update_opportunity` を呼ぶ
5. 検証エラーでは、返された項目をすべて修正し、同じ `request_id` で再試行する

`add_opportunity` と `update_opportunity` の `payload` では、日付を `YYYY-MM-DD`、URLを `https` で指定します。更新は部分更新ではなく全項目置換のため、`get_opportunity` で現在値を取得してから送ってください。状況や締め切りだけを直す場合は `update_recruitment_status` を使います。

同じ企業の同名イベントを新規登録しようとすると、既存の登録を示して拒否します。別日程・別コースとして意図的に分ける場合だけ、`add_opportunity` の `allow_duplicate` を `true` にしてください。

## 内部REST API

REST APIは公開せず、Next.jsサーバーと運用コマンドだけが`X-Internal-API-Token`ヘッダーを付けて利用します。ブラウザはrelua APIへ直接接続せず、必要な公開情報だけをNext.jsの同一オリジン経由で取得します。

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
- `/import#c=...`: 別端末の保存データを確認後にマージ
- `/import`: 受け取った引き継ぎリンクを貼り付けて、内容確認画面を開く
- `/list#l=...`: ログイン不要の共有リスト

引き継ぎリンクと共有リンクは、募集情報のUUIDではなく8文字の公開コード（`public_code`）を並べて表現します。固定長のため区切り文字を必要とせず、2,000バイトのリンクにおよそ240件が収まります。以前のUUID形式（`#b=`、`#jobs=`）のリンクも引き続き読み込めます。

QRコードはブラウザ内で生成します。URLフラグメントはサーバーへ送信されず、インポート時は存在する募集IDだけを既存データへ追加します。

これはリアルタイム同期ではなく、その時点の保存内容を別端末へマージする「引き継ぎ」です。引き継ぎ前には新規・保存済み・終了済みの件数と追加対象を確認できます。URLやQRコードの安定動作範囲を超える場合は、JSONバックアップを利用します。

## 運用

締切日を過ぎた募集の状態を更新します。cronやコンテナ基盤のスケジューラーから1日1回実行してください。

```bash
docker compose exec api python -m app.scripts.close_expired
```

OAuthで接続中のクライアントを確認し、不要になった接続を切ります。

```bash
docker compose exec api python -m app.scripts.mcp_connections list
docker compose exec api python -m app.scripts.mcp_connections revoke <grant_id>
docker compose exec api python -m app.scripts.mcp_connections purge
```

`revoke` は1回のログインで発行されたトークンをまとめて失効させ、そのクライアントを切断します。パスワードが漏れた疑いがあるときは、`MCP_OPERATOR_PASSWORD` の変更に加えて既存の接続も失効させてください。

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
- PostgreSQLとRedisの公開ポートを追加しない
- FastAPIとNext.jsの前段でTLS、CDN、リクエストサイズ制限を設定する
- OAuthを使わない場合は、MCP接続にSSHポートフォワードまたは運営者専用VPNを使用する
- OAuthを使う場合は、`MCP_PUBLIC_URL`をhttpsの実ホスト名にし、`MCP_OPERATOR_PASSWORD`を推測できない値にする（開発用の値のままではAPIが起動しない）
- OAuthを使う場合は、リバースプロキシで `/mcp`、`/oauth`、`/.well-known` だけを公開し、`/api/v1` は公開しない
- 実在企業10社分をChatGPT・Claudeの両方から登録し、要件定義書17.4の受入試験を行う
