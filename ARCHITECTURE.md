# relua アーキテクチャ

この文書は、実装を読む順番と責務境界を示すための設計索引です。利用者向けの操作手順は [`README.md`](./README.md)、コード上の動作はリンク先の実装とテストを正本とします。

## 1. システムの要約

relua は、ログインなしで閲覧できる募集情報の公開サイトと、運営者だけが書き込める MCP 接続を持つサービスです。ユーザーアカウントやサーバー側ブックマークはありません。

```text
閲覧者ブラウザ
    │ HTTPS
    ▼
Nginx / relua.conf ────────────────┐
    │                              │
    │ 公開画面                      │ /mcp, /oauth, /.well-known
    ▼                              ▼
Next.js frontend              FastAPI backend
    │ server-only BFF              │ REST / MCP / OAuth
    │ X-Internal-API-Token         │ 認証・検証・監査・冪等化
    └───────────────► PostgreSQL ◄─┘
                            ▲
                            │
                         Redis
                 レート制限／マスタキャッシュ
```

ローカルの Compose では、`frontend`、`api`、`db`、`redis` が分離されます。`api` と `frontend` のホスト公開ポートは既定でループバックのみです。公開構成では [`relua.conf`](./relua.conf) が `/mcp` と OAuth のディスカバリ・認可ルートだけを FastAPI に渡し、通常の `/` は Next.js に渡します。

## 2. フロントエンド

### 2.1 実行モデル

- Next.js App Router の Server Components が一覧・詳細・静的ページを描画する。
- [`frontend/lib/api.ts`](./frontend/lib/api.ts) は `server-only` で、`API_INTERNAL_URL` の FastAPI に `X-Internal-API-Token` を付けてアクセスする。ブラウザから FastAPI や内部トークンを直接見せない。
- [`frontend/app/api/opportunities/[id]/route.ts`](./frontend/app/api/opportunities/[id]/route.ts) は、保存データを復元する画面が同一オリジンから1件ずつ取得するための薄いプロキシである。
- [`frontend/lib/browser-api.ts`](./frontend/lib/browser-api.ts) はその route handler を最大8件ずつ呼び、見つからないIDと一時取得失敗を分ける。
- 画面固有の操作・表示は `frontend/components/`、検索パラメータ・表示整形・SEOは `frontend/lib/` に置く。
- `next.config.ts` は standalone 出力を使う。Docker build 時の `API_INTERNAL_URL` と `NEXT_PUBLIC_SITE_URL` は `frontend/Dockerfile` の build args から埋め込まれる。

### 2.2 画面と責務

| URL | 主なファイル | 責務 |
| --- | --- | --- |
| `/` | `frontend/app/page.tsx` | 公開一覧、検索、絞り込み、並び替え、カード／リスト／カレンダー表示 |
| `/opportunities/[id]` | `frontend/app/opportunities/[id]/page.tsx` | 詳細、SEOメタデータ、保存、カレンダー登録 |
| `/saved` | `frontend/app/saved/page.tsx`, `components/saved-dashboard.tsx` | ブックマーク、最近見た募集、JSON/CSV、共有・QR |
| `/import` | `frontend/app/import/page.tsx`, `components/import-bookmarks.tsx` | 引き継ぎリンクの確認と localStorage へのマージ |
| `/list` | `frontend/app/list/page.tsx`, `components/shared-opportunity-list.tsx` | 共有リンクから募集を読み込む |
| `/about`, `/terms`, `/policy` | 各 `page.tsx` | サービス説明、利用規約、プライバシー説明 |
| `/sitemap.xml`, `/robots.txt` | `sitemap.ts`, `robots.ts` | SEO用の公開URL |

### 2.3 ブラウザ内データ

[`frontend/lib/local-data.ts`](./frontend/lib/local-data.ts) が保存方式の正本です。

- `relua.bookmarks.v1` は募集のID、`relua.recents.v1` は最大30件の閲覧履歴を保持する。
- サーバーへ送るのは、共有・引き継ぎリンクから表示対象を取得するときだけで、保存・解除そのものは送信しない。
- 新しい共有リンクは8文字の `public_code` を区切りなしでフラグメントに並べる。旧UUID形式（`#b` / `#jobs`）も読み込む。
- `/import` は同一オリジン・正しいパス・長さを確認してから最大8件ずつ取得し、存在しないIDと取得失敗を区別する。
- URLフラグメントはHTTPリクエストに含まれないため、保存リストをサーバーログへ送らない。リンクが長すぎる場合はJSON/CSVバックアップを使う。

## 3. バックエンド

### 3.1 起動と認証の入口

[`backend/app/main.py`](./backend/app/main.py) が FastAPI、MCP HTTP transport、OAuth router、認証ミドルウェアを組み立てます。

1. `/api/v1/*` は `X-Internal-API-Token` が必要。
2. `/mcp` は固定 Bearer トークンを既定とし、`MCP_OAUTH_ENABLED=true` では OAuth access token も受け付ける。
3. OAuth 有効時だけ `/.well-known/*` と `/oauth/*` を認証前に公開する。
4. OAuth 有効時、MCPの初期化・ツール一覧・匿名読み取りツールだけは未認証で許可する。書き込みツールは401の `WWW-Authenticate` から OAuth を開始する。
5. FastAPI の OpenAPI/Swagger は無効化されている。公開APIは意図した REST、MCP、OAuth のみである。

### 3.2 REST API

| ルート | 実装 | 認証 | 用途 |
| --- | --- | --- | --- |
| `GET /api/v1/health` | `backend/app/api/health.py` | 内部トークン | ヘルスチェック |
| `GET /api/v1/masters` | `backend/app/api/masters.py` | 内部トークン | 固定値マスタ |
| `GET /api/v1/opportunities` | `backend/app/api/opportunities.py` | 内部トークン | 公開対象の検索・ページング |
| `GET /api/v1/opportunities/{id}` | 同上 | 内部トークン | UUIDまたは公開コードによる詳細 |
| `GET /api/v1/opportunities/{id}/same-company` | 同上 | 内部トークン | 同じ企業の公開募集 |

RESTの検索はページ番号を返します。既定では公開中かつ東京時間の当日以降が対象で、`q` がある場合は関連度、ない場合は締切順が基本です。MCPの検索は同じドメインサービスを使い、条件シグネチャとスナップショットを含む opaque cursor を返します。

### 3.3 MCP

[`backend/app/mcp_server.py`](./backend/app/mcp_server.py) はツールのスキーマ、`title`、annotations、output schema、認証要否、DBセッション境界を定義します。

| ツール群 | 主な処理 | 認証 |
| --- | --- | --- |
| 検索・詳細・マスタ | `search_opportunity`, `get_opportunity`, `get_master_values`, `get_sectors` | 不要（OAuth有効時の匿名公開にも対応） |
| 重複・企業同一性 | `find_similar_opportunities`, `find_opportunities_by_source_url`, `resolve_company`, `add_company_alias`, `merge_company` | 前者2つは不要、企業の候補確認・別名・物理統合の書き込みは必要 |
| 募集書き込み | `validate_opportunity`, `add_opportunity`, `upsert_opportunity`, `update_opportunity`, patch/status | 必要 |
| 削除・履歴 | delete preview/delete/restore/recent writes | 必要 |
| 収集キュー | target/source/check の一覧、キュー、追加、更新、確認記録 | 必要 |
| OAuth接続管理 | `backend/app/scripts/mcp_connections.py` | サーバー上の運用コマンド |

書き込みツールは、入力を [`backend/app/schemas.py`](./backend/app/schemas.py) で検証し、ドメインエラーを構造化して返します。実際の保存や整合性処理は `mcp_server.py` に複製せず `backend/app/services/` へ委譲します。

### 3.4 ドメインサービス

| ファイル | 責務 |
| --- | --- |
| `services/opportunities.py` | 検索、関連度、カーソル、固定値解決、重複検出、書き込み、論理削除・復元、監査 |
| `services/companies.py` | 企業名の正規化、正式名・別名の完全一致、候補提示、別名の冪等書き込み |
| `services/company_industries.py` | 企業と複数業界・業種の分類を維持 |
| `services/collection_targets.py` | 企業単位の収集対象、情報源、確認履歴、優先度・次回確認日 |
| `services/masters.py` / `master_cache.py` | 固定値の解決とキャッシュ |
| `services/normalization.py` | 企業名、タグ、一次情報URLの正規化 |
| `services/oauth.py` | OAuth client、PKCE認可コード、access/refresh token、grant失効 |
| `services/rate_limit.py` | Redisの固定窓レート制限。OAuthログイン・動的登録などを保護 |
| `services/serialization.py` | DBモデルからREST/MCP/画面共通のレスポンスへ変換。公開詳細URLも生成 |
| `services/errors.py` | 固定値・入力エラーの共通メッセージ |

### 3.5 共通基盤と運用スクリプト

| ファイル | 責務 |
| --- | --- |
| `app/config.py` | 環境変数、URL由来の issuer/resource、production時の開発用秘密値拒否 |
| `app/db.py` | SQLAlchemy engine、session、Declarative Base、トランザクション境界 |
| `app/schemas.py` | REST/MCPのPydantic入力・出力、固定値型、入力制約 |
| `app/security.py` | 内部token、Bearer、operator password の比較とOAuth token hash |
| `app/master_data.py` | 新規DBへ固定値マスタを投入する定義 |
| `app/dates.py` | 東京時間を基準にした当日判定 |
| `app/scripts/close_expired.py` | 締切日を過ぎた公開募集の状況を更新 |
| `app/scripts/seed_demo.py` | 架空のUI確認用データを冪等的に投入 |
| `app/scripts/mcp_connections.py` | OAuth grant の一覧・失効・期限切れ掃除 |

## 4. データモデルと不変条件

定義の正本は [`backend/app/models.py`](./backend/app/models.py) です。ここでは関係を読むためのグループだけを示します。

### 4.1 固定値と募集

```text
industries ──< sectors
     │
     └──< company_industries >── companies ──< company_aliases
                              │
                              └──< opportunities
opportunities >── status / event_type / event_format / sector
opportunities >──< job_categories / graduation_years / degrees / tags
```

- `opportunities.id` は内部UUID、`public_code` は8文字のCrockford base32で、公開URL・共有リンクに使う。
- `Industry`、`Sector`、職種、卒業年、学位、募集状況、イベント種別、形式は固定値マスタ。募集書き込み時は指定業界に属する業種だけを受け付ける。
- 企業同一性は正規化正式名または明示登録した別名の完全一致を正本にする。部分一致・`pg_trgm` は候補提示と検索補助だけで、企業を自動統合しない。
- 企業は複数業界に属せる。`company_industries.is_primary` は1社につき高々1件で、単一分類表示用である。
- `source_url` は正規化した `normalized_source_url` と共に保存する。短縮URL、IP/localhost、求人集約・口コミサイトを情報源として拒否し、同じ一次情報URLは登録拒否ではなく確認用警告とする。

### 4.2 企業単位の収集

```text
companies ──1:1── collection_targets ──< collection_sources
                                  └──────< collection_checks ──?── opportunities
```

- `collection_targets` は1企業につき1件。複数業界の分類は `company_industries` に置き、同じ企業を二重巡回・二重計上しない。
- `collection_targets.is_active` と各 source の `is_active` は無効化で保持する。削除ではなく運用状態を表す。
- 募集書き込みへ正しい `collection_target_id` を渡すと、募集保存と `found` 確認記録を同じトランザクションで作る。IDを省略した場合も企業一致で自動リンクできる。
- 採用ページ未登録、未確認、確認期限超過は収集キューの状態として返される。

### 4.3 書き込みの安全性

- `request_id` と payload hash を `idempotency_records`、企業別名・企業統合を `company_request_records`、収集操作を `collection_request_records` に記録する。同じID・同じ内容の再試行は前回結果を返し、内容や対象が違えば拒否する。
- 企業統合は明示した統合元IDの募集、別名、業界分類、収集対象・情報源・確認履歴を統合先へ移し、統合元のCompanyを物理削除する。監査ログは不変の履歴として旧IDを保持する。名前の類似だけで自動統合しない。
- 成功・失敗を `audit_logs` に記録する。現状は閲覧画面や自動ロールバックを持たないため、運用確認は MCP の履歴ツールまたはDBで行う。
- 全項目更新は `get_opportunity` で最新値を取得してから送る。部分更新・削除は `expected_updated_at` で楽観ロックし、取得後の別更新による上書きを拒否する。
- 削除は `deleted_at` を設定する論理削除。通常の検索・詳細から隠し、復元時は同じUUID・公開コードを維持する。復元時にも公開中の同名重複を再確認する。
- 同一企業の同名イベントは既定で拒否し、別日程等として意図的に分ける場合だけ `allow_duplicate` を明示する。

### 4.4 OAuthデータ

`oauth_clients`、`oauth_authorization_codes`、`oauth_tokens` が OAuth の状態を保持します。認可コードはPKCE必須、tokenはハッシュのみ保存、refresh token の再利用は grant 全体を失効させます。接続は `mcp_connections` スクリプトで一覧・失効・期限切れ掃除を行います。

## 5. リクエスト経路

### 5.1 公開閲覧

```text
Browser → Next Server Component → frontend/lib/api.ts
       → GET /api/v1/opportunities (internal token)
       → FastAPI middleware → search_opportunities
       → SQLAlchemy → PostgreSQL
       ← serialization → Next.js HTML/metadata
```

ブラウザのURLクエリは Next.js が許可された検索パラメータへ変換します。画面の「保存」はDBへ行かず、詳細の共有対象だけが同一オリジンの route handler 経由で取得されます。

### 5.2 MCP書き込み

```text
MCP client → /mcp → static Bearer または OAuth access token
           → mcp_server tool
           → Pydantic input / fixed master / source validation
           → domain service transaction
           → company lock + duplicate check + idempotency + audit
           → PostgreSQL commit
```

失敗時はDBを rollback して監査記録を残します。再試行は、検証エラーなら内容を直して新しい `request_id`、通信失敗などの同じ操作を再送する場合は同じ `request_id` を使う、という区別が重要です。詳細な診断は [`docs/knowledge/debugging.md`](./docs/knowledge/debugging.md) を参照します。

### 5.3 OAuth接続

```text
MCP client
  → 401 + resource_metadata
  → /.well-known discovery
  → /oauth/register (client + callback + PKCE)
  → /oauth/authorize (operator password)
  → redirect with code
  → /oauth/token (code_verifier)
  → /mcp with access token
```

`MCP_PUBLIC_URL` が issuer/resource の正本です。公開時はTLS終端プロキシを置き、`FORWARDED_ALLOW_IPS` を実際のプロキシIPに合わせます。

## 6. DB、マイグレーション、インフラ

### 6.1 マイグレーション

- `backend/alembic/versions/20260726_0001_initial.py` は ORM metadata から新規DBを作り、固定値を投入する。
- 以降の migration は既存DBへ段階的に適用する。特に関連コードが新規DBで既に存在し得るため、後続 migration は存在確認や dialect 分岐を持つ。
- `20260814_0009_add_relevance_search.py` と `20260820_0013_add_company_identity_tools.py` は PostgreSQL の `pg_trgm` と GIN index を使う。SQLiteのテストは近似検索へフォールバックするため、移行と本番検索を同一視しない。
- `20260820_0012_add_company_industries.py` は、旧来の業界単位収集対象を1社1対象へ統合し、分類を `company_industries` へ移すデータ移行である。

スキーマを変更するときは ORM、migration、fresh DB、既存DB upgrade、必要な回帰テストを一緒に確認します。

### 6.2 Composeと公開境界

| 構成要素 | 定義 | 役割 |
| --- | --- | --- |
| `db` | `docker-compose.yml` | PostgreSQL 16、永続 volume `postgres_data` |
| `redis` | `docker-compose.yml` | Redis 7、レート制限、永続 volume `redis_data` |
| `api` | `backend/Dockerfile` | Alembic後に Uvicorn/FastAPI を8000番で起動 |
| `frontend` | `frontend/Dockerfile` | Next standalone を3000番で起動 |
| Nginx | `relua.conf` | TLS、公開MCP/OAuth、Next.jsへのルーティング、MCPストリーミングの非バッファリング |

環境変数の一覧と開発値は [`.env.example`](./.env.example)、起動手順は [`README.md`](./README.md) を正本とします。実際の秘密値は `.env` に置き、コミットしません。

### 6.3 CI/CD

[`.github/workflows/ci.yml`](./.github/workflows/ci.yml) の正本は次の3段階です。

- backend: Ruff、SQLite単体テスト、PostgreSQL Alembic upgrade、`pg_trgm`／関連度の確認。
- frontend: `npm ci`、lint、production build。
- main push: SSH先で `docker compose up -d --build`、サービス状態を確認し、失敗時は直前コミットへ戻して再起動する。

## 7. 変更時のソースマップ

| 変更したいもの | 最初に読むコード | 同時に確認するもの |
| --- | --- | --- |
| 公開一覧・詳細 | `frontend/app/`, `frontend/components/`, `frontend/lib/api.ts` | `backend/app/api/opportunities.py`, frontend tests |
| 保存・共有・QR | `frontend/lib/local-data.ts`, `components/saved-dashboard.tsx` | `backend/app/services/serialization.py`, local-data/UI tests |
| RESTのレスポンス | `backend/app/api/`, `schemas.py`, `services/serialization.py` | `frontend/lib/types.ts`, API呼び出し、認証ヘッダー |
| 検索・重複・書き込み | `backend/app/services/opportunities.py` | `schemas.py`, `mcp_server.py`, `test_opportunities.py`, `test_mcp_tools.py` |
| 企業同一性・別名 | `services/companies.py`, `company_industries.py` | `models.py`, identity/collection tests、関連ADR |
| 収集キュー | `services/collection_targets.py` | `models.py`, `test_collection_targets.py`, MCP tool definitions |
| OAuth・MCP認証 | `main.py`, `api/oauth.py`, `services/oauth.py`, `mcp_server.py` | `test_oauth.py`, `test_oauth_endpoints.py`, `relua.conf` |
| 共通基盤・運用ジョブ | `config.py`, `db.py`, `schemas.py`, `security.py`, `dates.py`, `scripts/` | `.env.example`, Compose、該当サービスのテスト |
| DBスキーマ | `models.py`, 最新 migration | 0001 fresh DB、全 upgrade、PostgreSQL CI |
| デプロイ・公開境界 | `docker-compose.yml`, Dockerfiles, `relua.conf`, CI | `.env.example`, READMEの本番設定 |

## 8. ドキュメントの使い分け

- 構造を探すときはこの文書。
- コマンドや運用手順を実行するときは [`README.md`](./README.md)。
- 同じ問題を再現・切り分けるときは [`docs/knowledge/debugging.md`](./docs/knowledge/debugging.md)。
- 設計を変えるか迷ったときは [`docs/decisions/README.md`](./docs/decisions/README.md) と関連ADR。

新しい文書は、既存文書に書かれた事実を転載するのではなく、責務・理由・再利用可能性のいずれかを補う場合だけ追加します。
