# relua

インターン・本選考情報を、ログインなしで検索できる公開型の就活情報サービスです。募集情報の追加・更新・削除・復元は運営者本人の認証済みMCP接続に限定し、固定値マスタ、厳格な入力検証、冪等性、監査ログによってデータ品質を保ちます。

このリポジトリは **v0.1（MVP）** と、ローカル保存・端末間共有機能を実装しています。ユーザーアカウントやサーバー側ブックマークは設けていません。実装の構造は [`ARCHITECTURE.md`](./ARCHITECTURE.md)、Codexの作業入口は [`AGENTS.md`](./AGENTS.md) を参照してください。

開発者向け資料は、再利用可能な診断方法を [`docs/knowledge/`](./docs/knowledge/)、技術判断を [`docs/decisions/`](./docs/decisions/) に分離しています。

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
  - Bearerトークン認証、request IDによる冪等化、同名イベントの重複検出、成功・失敗監査ログ
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
| `search_opportunity` | 不要 | キーワードを関連度順で検索し、固定値で絞り込んだ概要をカーソル方式で返す |
| `get_opportunity` | 不要 | IDまたは公開コードで1件を全項目取得する |
| `get_master_values` | 不要 | 選択可能な固定値マスタを全件返す |
| `get_sectors` | 不要 | 指定した業界に属する業種だけを返す |
| `find_similar_opportunities` | 不要 | 同じ企業の登録済み募集を探し、二重登録を防ぐ |
| `find_opportunities_by_source_url` | 不要 | 計測パラメータ等を除いた一次情報URLで既存募集を探す |
| `resolve_company` | 必要 | 正式名・別名の完全一致を優先し、部分一致・タイプミスの企業候補を確認用に返す |
| `add_company_alias` | 必要 | 公式情報で同一企業と確認した略称・英語名・旧社名を登録する |
| `delete_company_alias` | 必要 | 誤登録された企業別名を削除する |
| `validate_opportunity` | 必要 | 保存せずに検証し、固定値の誤りと重複の疑いを返す |
| `add_opportunity` | 必要 | 募集情報を1件追加する |
| `update_opportunity` | 必要 | 既存の募集情報を全項目置換で更新する |
| `preview_opportunity_patch` | 必要 | 部分更新を保存せず検証し、変更差分と警告を返す |
| `patch_opportunity` | 必要 | 楽観ロック付きで指定項目だけを更新する |
| `update_recruitment_status` | 必要 | 募集状況と締め切りだけを更新する |
| `verify_opportunity` | 必要 | 一次情報に変更がないことだけを記録し、最終確認日時を更新する |
| `preview_delete_opportunity` | 必要 | 削除対象と公開表示・関連履歴への影響を保存せず確認する |
| `delete_opportunity` | 必要 | 楽観ロック付きで募集情報を公開データから論理削除する |
| `restore_opportunity` | 必要 | 論理削除した募集を同じID・公開コードのまま復元する |
| `list_recent_writes` | 必要 | 直近の登録・更新・削除・復元の記録を返す |
| `list_stale_opportunities` | 必要 | 日付と「募集中」の矛盾を最優先に、公式情報の再確認が必要な募集を取得する |
| `list_collection_targets` | 必要 | 情報収集対象の企業を検索・一覧する（採用ページ未登録の対象だけの抽出を含む） |
| `list_unmonitored_companies` | 必要 | 企業マスタにあり、まだ情報収集対象を持たない企業を一覧する |
| `get_collection_target` | 必要 | 収集対象、公式ページ、登録済み募集を1件取得する |
| `get_company_maintenance_context` | 必要 | 企業の全募集、公式URL、各募集の最終確認日時をまとめて取得する |
| `get_collection_queue` | 必要 | 未確認または再確認期限を過ぎた企業を優先度順に返す |
| `list_collection_checks` | 必要 | 企業ごとの情報収集・確認履歴を新しい順に返す |
| `add_collection_target` | 必要 | 既存CompanyのIDまたは新規企業名、所属業界、優先度、確認間隔、公式ページを収集対象へ追加する |
| `update_collection_target` | 必要 | 収集対象を部分更新または無効化する |
| `add_collection_source` | 必要 | 収集対象へ企業公式ページを追加する |
| `update_collection_source` | 必要 | 公式ページのURL・種類・有効状態を部分更新する |
| `record_collection_check` | 必要 | 募集の有無や確認不能などの確認結果と次回確認日を記録する |

`search_opportunity` の続きを取得するときは、応答の `next_cursor` を検索条件を変えずに次の呼び出しの `cursor` へ渡します。`next_cursor` が `null` になれば終端です。カーソルは検索開始時点と並び順を保持するため、取得済みの募集を途中で削除してもページ境界がずれません。

書き込みツールは運営者本人の認証済み接続だけが呼べるため、1分あたりの操作上限は設けていません。大量登録・一括更新でも各操作の入力検証、request IDによる冪等化、監査ログは通常どおり適用されます。OAuthのログイン試行と動的クライアント登録には、公開エンドポイントを保護するための回数制限を引き続き適用します。

各ツールは `title`、`annotations`（`readOnlyHint` など）、`outputSchema` を公開します。読み取り専用かどうかがクライアント側で判別できるため、ChatGPTやClaudeは読み取りツールの自動承認を判断できます。

すべての募集情報には詳細ページのURL（`url`）が含まれます。組み立てには `NEXT_PUBLIC_SITE_URL`（APIコンテナには `SITE_URL`）を使うため、公開環境では実際のサイトURLを設定してください。

推奨操作順は次のとおりです。

1. `get_master_values` で選択可能な固定値を取得し、業種は `get_sectors` で業界配下に絞る
2. 企業名が略称・英語名・誤記の可能性がある場合は `resolve_company` で候補を取得する
3. 部分一致・曖昧一致の候補を公式情報で同一企業と確認できた場合だけ `add_company_alias` で別名を登録する
4. `find_similar_opportunities` と `find_opportunities_by_source_url` で同じ募集が登録済みでないか確認する
5. 内容に自信がない場合は `validate_opportunity` で先に検証する
6. `add_opportunity` または `update_opportunity` を呼ぶ
7. 検証エラーでは、返された項目をすべて修正し、同じ `request_id` で再試行する

企業の自動的な同一視に使うのは、正規化した正式名または登録済み別名の完全一致だけです。部分一致と
PostgreSQL `pg_trgm` によるタイプミス検索は候補提示に限られ、MCPが勝手に企業を統合することはありません。
別名の追加・削除は監査ログへ記録され、`request_id` により安全に再試行できます。

`add_opportunity` と `update_opportunity` の `payload` では、日付を `YYYY-MM-DD`、URLを `https` で指定します。更新は部分更新ではなく全項目置換のため、`get_opportunity` で現在値を取得してから送ってください。状況や締め切りだけを直す場合は `update_recruitment_status` を使います。公式ページを再確認して内容が変わっていない場合は、登録済みの一次情報URLと確認日時を `verify_opportunity` へ渡してください。これは `source_checked_at` のみを更新し、監査ログでは状況更新と区別されます。

その他の一部項目だけを直す場合は、`get_opportunity` が返す `updated_at` と変更項目を `preview_opportunity_patch` へ渡し、差分を確認してから同じ内容を `patch_opportunity` へ渡します。サーバー側で現在値とマージした後に全項目を検証します。取得後に別の更新があった場合は `expected_updated_at` の不一致として拒否されるため、古い値で上書きしません。

誤登録などを公開データから削除する場合は、`preview_delete_opportunity` で対象と影響を確認し、返された `id` と `expected_updated_at` を `delete_opportunity` へ渡します。取得後に更新された募集は削除を拒否します。削除は論理削除で、検索、詳細ページ、収集対象の登録済み募集一覧から隠れますが、募集情報、収集確認履歴との関連付け、監査ログは保持されます。

誤って削除した場合は、削除結果または `list_recent_writes` で確認できる募集情報IDを `restore_opportunity` へ渡します。元のUUIDと公開コードを維持するため、復元後は既存のブックマークと共有リンクも再び利用できます。削除と復元はいずれも `request_id` で冪等化されます。

`source_url` には企業自身の採用ページなど一次情報を指定します。求人サイト・就活情報サイト・口コミサイトのURLは拒否されます。これらの掲載内容は各社が構築したデータベースであり、規約上も自動的な再利用が認められていないためです。自由記述の項目には出典の文章を転記せず、日程・対象・報酬などの事実だけを要約して記載し、担当者名などの個人名と個人宛の連絡先は含めません。

同じ企業の同名イベントを新規登録しようとすると、既存の登録を示して拒否します。別日程・別コースとして意図的に分ける場合だけ、`add_opportunity` の `allow_duplicate` を `true` にしてください。

一次情報URLは、ホスト名の大文字小文字、末尾スラッシュ、フラグメント、既知の計測パラメータを除いて照合します。同じ公式ページに複数募集が掲載される場合があるため、URL一致は一律の登録拒否ではなく、既存募集を確認するための警告として扱います。

### 企業単位の情報収集キュー

運営者用MCPでは、募集がまだ登録されていない企業も収集対象として管理できます。収集優先度は企業の評価や公開ランキングではなく、公式ページを確認する内部の作業順です。収集対象の読み取りを含め、これらのツールはすべて認証を必要とします。

収集対象は**1企業につき1件**です。事業が複数業界にまたがる企業は、収集対象を分けるのではなく `industries` に複数の業界・業種を指定します（例: Ubie株式会社は IT・通信/AI と 医療・製薬/ヘルスケア）。先頭が代表の業界として扱われ、`industry` での絞り込みはそのいずれかに一致すれば該当します。収集対象の件数がそのまま企業数になり、同じ採用ページを二重に巡回することもありません。募集情報を登録すると、その募集の業界・業種も企業の分類へ自動的に加わります。

推奨操作順は次のとおりです。

1. 既存の企業は `list_unmonitored_companies` でIDを確認し、`add_collection_target` の `company_id` で、所属業界、優先度、確認間隔、1件以上の企業公式ページを登録する。新規企業だけは `company_name` を指定する（両方は指定しない）
2. `get_collection_queue` で未確認または次回確認期限を過ぎた企業を取得する
3. 公式ページを確認し、`find_similar_opportunities` と `find_opportunities_by_source_url` を経て募集を追加または更新する
4. 募集を追加・更新する場合は `collection_target_id` を渡し、募集と確認結果 `found` を同じトランザクションで記録する
5. 募集がない場合は `record_collection_check` で `no_opening`、`unreachable`、`needs_review` のいずれかを記録する

収集対象の更新は部分更新です。省略した項目は維持され、`selection_reason` は明示的に `null` を指定すると解除されます。`industries` だけは例外で、指定した内容で分類を全置換します（業界を追加する場合は既存の業界も併せて送ります）。収集を止める場合はデータを削除せず、`update_collection_target` で `is_active` を `false` にします。公式ページも同様に `update_collection_source` で無効化できます。すべての書き込みは `request_id` で冪等化され、監査ログに記録されます。

企業トップページしか登録されていない収集対象は、巡回しても新しい募集が現れないため `has_primary_source: false` として報告されます。`list_collection_targets` に `source_gap=true` を渡すとその対象だけを取り出せ、`missing_source_types` が未登録の公式ページ種別（`recruit`、`internship`、`event`、`news`）を示します。確認中に採用ページを見つけた場合は、`record_collection_check` の `discovered_sources` へ渡すと確認結果の記録と同時に情報源として追加されます。

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

運営者は毎日 `list_stale_opportunities` を確認してください。東京基準で、`deadline < today` または `event_end_date < today` なのに募集状況が「募集中」の募集を最優先で返します。締切延長や追加募集の可能性があるため、Reluaはこの矛盾を自動で「締切」に変更しません。公式ページを確認し、変更がなければ `verify_opportunity`、変更があれば適切な更新ツールを実行してください。

cronやコンテナ基盤のスケジューラーから次を1日1回実行してください。これはすでに論理削除した募集を、削除から30日後に完全削除します。期限超過だけで募集を論理削除することはありません。完全削除後は復元できません。収集確認履歴は残りますが、削除済み募集への参照は解除されます。

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
- 実在企業10社分をChatGPT・Claudeの両方から登録し、運用上の受入確認を行う
