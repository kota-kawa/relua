# API 契約とマイグレーションの注意点

`backend/app/schemas.py`、`backend/app/mcp_server.py`、`backend/app/models.py`、`backend/alembic/versions/` に触るときに読みます。現在の契約そのものは実装とテスト、構造は [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) §4／§6.1、判断の理由は関連 ADR を参照してください。

## 1. 契約の所在

| 契約 | 正本 | 利用側 | 固定するテスト |
| --- | --- | --- | --- |
| 内部 REST（`/api/v1/*`） | `backend/app/api/`、`schemas.py`、`services/serialization.py` | `frontend/lib/api.ts`、`frontend/lib/types.ts`、運用スクリプト | `backend/tests/test_opportunities.py`、`test_company_pages.py`、`frontend/lib/api.test.ts` |
| MCP ツール | `backend/app/mcp_server.py` のツール定義（名前、引数、説明文、認証要否） | ChatGPT・Claude などの外部クライアント | `backend/tests/test_mcp_tools.py` |
| OAuth／認証 | `main.py`、`api/oauth.py`、`services/oauth.py` | 外部 MCP クライアント、`relua.conf` | `test_oauth.py`、`test_oauth_endpoints.py`、`test_security.py`、`test_rate_limit.py` |
| 公開 URL | `frontend/proxy.ts`、`frontend/lib/site.ts`、`frontend/lib/seo.ts`、サイトマップ | 検索エンジン、MCP が返す詳細 URL | `frontend/proxy.test.ts`、`lib/seo.test.ts`、`app/sitemap.test.ts` |
| 環境変数 | `.env.example` | `config.py`、`docker-compose.yml`、frontend の `process.env` | `python3 scripts/check_env_documentation.py` |

## 2. REST を変えるとき

- レスポンスの追加は後方互換ですが、削除・型変更・意味変更は `frontend/lib/types.ts` と呼び出し側を同じ PR で更新します。frontend は Data Cache にスナップショットを保存するため、デプロイ直後は古い形のスナップショットと新しいコードが同居しうることを踏まえ、欠けた項目で落ちない実装にします。
- クエリパラメータの検証エラー（422）は frontend 側で 400／404 相当に正規化し、500 にしません。新しいパラメータを追加したら不正値のテストも足します。
- 一覧 API の件数・並び・index 条件（`indexable=true` など）はサイトマップと metadata が同じ値を読みます。片方だけ変えると robots とサイトマップが食い違います。

## 3. MCP ツールを変えるとき

- ツールの説明文と引数スキーマは、AI クライアントが「いつ・どう呼ぶか」を決める材料です。変更したら `test_mcp_tools.py` を回し、`README.md` の「MCPツール」表を同期します。
- 認証要否は登録時に決まります。読み取り専用で公開情報だけを返すツール以外を匿名にしません。
- 書き込みツールの入力は `schemas.py` で検証し、日本語の項目名は `services/errors.py` の `FIELD_LABELS` に追加します。配列内の項目は `主な事業[0].内容` の形で位置を返します。
- 既存行を変えるツール（update／patch／delete／restore／status 更新）は `expected_updated_at` を必須にし、`FOR UPDATE` で行を取ります（ADR-0002）。新しい更新経路を足すときに省くと、過去に実際に起きた lost update が再発します。
- 再試行の冪等化は `request_id`＋payload の一致で判定します。payload に含める値の正規化（UTC 化、並び順）を変えると、同じ再試行が別操作と見なされます。
- 一次情報の確認（`verify_opportunity`、`record_collection_check`）だけが `source_checked_at` と確認履歴を動かします。内容更新のツールにこの副作用を持たせません（ADR-0010）。
- 例外はツールごとに捕まえず、登録時の共通境界に任せます（ADR-0020）。境界を通さないツールを増やすと、SQL やバインド値が応答に出ます。

## 4. マイグレーションの規則

### 番号と連鎖

- ファイル名は `YYYYMMDD_NNNN_<snake_case>.py`、`revision` は `YYYYMMDD_NNNN`、`down_revision` は現在の唯一の head です。
- 着手時と PR 作成前に `alembic heads` が 1 本であることを確認します。並列作業で head が 2 本になった場合は、後から取り込む側が `down_revision` を付け替えます（マージ migration は作りません）。
- 連番が重複しても連鎖が正しければ動きますが（過去に `0010` が 2 つある）、新規に作るときは既存の最大連番＋1 にします。

### 新規 DB と既存 DB の両方で動くこと

- `20260726_0001_initial.py` は現行の ORM metadata で `create_all` します。したがって新規 DB では、後続 migration が追加する列・索引・テーブルが既に存在します。後続 migration は `inspect` で存在確認してからスキップします。
- 生 SQL でデータを投入する migration は、後から追加された NOT NULL 列を埋める必要があります。列の有無を確認してから値を補います。
- PostgreSQL 専用の extension（`pg_trgm`）や GIN 索引は dialect で分岐し、SQLite では実行しません。確認は CI の PostgreSQL ジョブと `tests/test_pg_trgm_migration.py` です。
- 最低チェックは、空の SQLite、空の PostgreSQL への `upgrade head`、既存データを含む PostgreSQL への upgrade、`downgrade -1` と再 upgrade、対象サービスの回帰テストです。

### データ移行

- 正規化やバックフィルはアプリの関数（`services/normalization.py` など）を import して使い、migration に別実装を置きません。
- 修復できない行（正規化後に一意制約へ衝突する行など）は据え置き、WARNING で対象を名指しします。例外で止めると、`alembic upgrade head && uvicorn` の起動コマンドが止まり、サイト全体が落ちます。
- 一意制約のある列を一括で書き換えるときは、一意のプレースホルダへ退避してから確定値を入れる 2 段階にし、更新順序に依存させません。
- 複数行を 1 行へ統合する移行（収集対象の 1 社 1 対象化など）は、移動する子レコードと捨てる重複を明示し、PostgreSQL の実データ相当で upgrade-in-place と fresh の両方向を確認します。

### 適用済み migration を書き換えない

- 適用済みの migration は結果を変える編集をしません。新しい変更は新しい migration にします。
- 唯一の例外は「新規 DB でだけ失敗する」不具合の修正で、既存 DB での結果を変えない存在確認の追加に限ります。過去の例は `0003` の列存在確認と `0010` の seed の `public_code` 補完です。
- 例外を使った場合は、PR 本文に「このリビジョンを通過済みの既存 DB には影響しない」ことと確認方法を書きます。

## 5. 契約変更の PR に書くこと

- 互換性の区分（後方互換／利用側の同時更新が必要／データ移行あり）。
- 実行した確認（SQLite のテスト、PostgreSQL 実機の upgrade／downgrade、`test_pg_trgm_migration.py`）。
- デプロイ前後にサーバーで必要な作業（`.env` の追加、手動の `merge_company` など）。
