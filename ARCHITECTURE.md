# relua アーキテクチャ

この文書は、実装を読む順番と責務境界を示すための設計索引です。利用者向けの操作手順は [`docs/usage.md`](./docs/usage.md)、コード上の動作はリンク先の実装とテストを正本とします。

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

ローカルの Compose では、`frontend`、`api`、`db`、`redis` が分離されます。`api` と `frontend` のホスト公開ポートは既定でループバックのみです。公開構成では [`relua.conf`](./relua.conf) が `/mcp` と OAuth のディスカバリ・認可ルートだけを FastAPI に渡し、通常の `/` は Next.js に渡します。論理削除済みデータの完全削除は [Daily Maintenance](./.github/workflows/maintenance.yml) が日次実行し、Actionsの成否を監視記録にします。

## 2. フロントエンド

### 2.1 実行モデル

- Next.js App Router の Server Components が一覧・詳細・静的ページを描画する。
- [`frontend/lib/api.ts`](./frontend/lib/api.ts) は `server-only` で、`API_INTERNAL_URL` の FastAPI に `X-Internal-API-Token` を付けてアクセスする。ブラウザから FastAPI や内部トークンを直接見せない。
- [`frontend/app/api/opportunities/[id]/route.ts`](./frontend/app/api/opportunities/[id]/route.ts) は、保存データを復元する画面が同一オリジンから1件ずつ取得するための薄いプロキシである。
- [`frontend/lib/browser-api.ts`](./frontend/lib/browser-api.ts) はその route handler を最大8件ずつ呼び、見つからないIDと一時取得失敗を分ける。
- 画面固有の操作・表示は `frontend/components/`、検索パラメータ・表示整形・SEOは `frontend/lib/` に置く。
- [`frontend/lib/site.ts`](./frontend/lib/site.ts) が公開originと公開コード詳細pathの正本で、[`frontend/proxy.ts`](./frontend/proxy.ts) が`www`と旧UUID詳細を描画前にcanonical URLへ308転送する。
- [`frontend/lib/seo-data.ts`](./frontend/lib/seo-data.ts) が一覧・詳細のmetadataと本文で共有する完全成功スナップショットを管理する。60秒で再検証し、最後の正常取得から1時間まで利用できる。1時間を超えた値は返さず、Data Cacheが実行中の再検証に相乗りして最新データを待つ。API fetchは`no-store`で、冷たいキャッシュの失敗も再取得の失敗も5xxへ伝播する。
- `next.config.ts` は standalone 出力を使う。Docker build 時の `API_INTERNAL_URL` と `NEXT_PUBLIC_SITE_URL` は `frontend/Dockerfile` の build args から埋め込まれる。

### 2.2 画面と責務

| URL | 主なファイル | 責務 |
| --- | --- | --- |
| `/` | `frontend/app/page.tsx` | 公開一覧、検索、絞り込み、並び替え、カード／リスト／カレンダー表示 |
| `/opportunities/[id]` | `frontend/app/opportunities/[id]/page.tsx` | 公開コードをcanonicalとする詳細、SEOメタデータ、構造化データ、保存、カレンダー登録。旧UUIDはproxyで転送 |
| `/companies` | `frontend/app/companies/page.tsx` | プロフィールを持つ全企業のディレクトリ。名前順、1ページ100件、範囲外と不正な`page`は404 |
| `/companies/[code]` | `frontend/app/companies/[code]/page.tsx` | 公開コードをcanonicalとする企業ページ。一言説明、事業内容の本文、主な事業、現在の募集、過去の募集、SEOメタデータ、構造化データ |
| `/saved` | `frontend/app/saved/page.tsx`, `components/saved-dashboard.tsx` | ブックマーク、最近見た募集、JSON/CSV、共有・QR |
| `/import` | `frontend/app/import/page.tsx`, `components/import-bookmarks.tsx` | 引き継ぎリンクの確認と localStorage へのマージ |
| `/list` | `frontend/app/list/page.tsx`, `components/shared-opportunity-list.tsx` | 共有リンクから募集を読み込む |
| `/about`, `/terms`, `/policy` | 各 `page.tsx` | サービス説明、利用規約、プライバシー説明 |
| `/sitemap.xml`, `/sitemaps/[page].xml`, `/robots.txt` | `app/sitemap.xml/route.ts`, `app/sitemaps/[page]/route.ts`, `lib/sitemap.ts`, `robots.ts` | 実行時の募集データと固定allowlistカテゴリから作るcanonical公開URL。45,000件までは単一 `urlset`、超過時は同じURLがサイトマップインデックスになる。部分失敗は503 |
| エラー境界 | `app/error.tsx` | 想定外の上流失敗を500ではなく再試行可能な画面に落とす |

企業ページは、一言説明（`business_summary`）と事業内容の本文（`description`）の両方が登録済みの企業だけをindex対象にし、それ以外は`noindex, follow`とする。現在の募集の有無は条件に含めない。募集の増減で同じURLがindexと`noindex`を往復しないためで、`/companies`のディレクトリが全企業ページへの恒久的な内部リンクを持つ（ADR-0023）。

一覧の自由検索、並び替え、複合ファセットは`noindex, follow`とし、範囲外ページは404とする。業界、業種、職種、募集種別、開催形式、卒業年度は、`frontend/lib/seo.ts`のレビュー済みallowlistにある単一条件だけをindex対象にし、正常結果が0件なら404とする。件数の5／8閾値は使わず、説明とカテゴリディレクトリをSSRする。詳細は募集予定・募集中・通年募集かつ締切前／未定だけをindex対象にする。

### 2.3 遷移中の表示とモーション

遷移中はルート直下に`loading.tsx`を置かず、routerが現在の画面を保持したままサーバー応答を待つ。詳細・範囲外ページで先にskeletonをストリーミングすると、ページ内の308／404がHTTP 200に変わるためである。フィードバックはroot layoutの進捗バーで示す。

- 同じ画面のURLだけを変える遷移（絞り込み・並び替え・表示切替・ページ送り）では、routerは新しい結果が揃うまで今の画面を出したままにする。押した側の状態と`RouteProgress`で反応を示す。
- 別ルートへの遷移（詳細ページなど）でも、現在の画面を出したまま応答を待つ。成功時は新しいページを表示し、旧UUIDの308や存在しないページの404はストリーミング前に確定させる。

| ファイル | 役割 |
| --- | --- |
| [`frontend/lib/navigation-progress.ts`](./frontend/lib/navigation-progress.ts) | 進行中の遷移数を持つモジュール内ストア。`useReportNavigation` で報告し、`useNavigationPending` で読む |
| [`frontend/components/nav-link.tsx`](./frontend/components/nav-link.tsx) | `useLinkStatus` を子から読み、そのリンクの遷移をストアへ報告する `next/link` |
| [`frontend/components/route-progress.tsx`](./frontend/components/route-progress.tsx) | root layout に1つだけ置く進捗バー。140ms未満の遷移では表示しない |
| [`frontend/components/view-switcher.tsx`](./frontend/components/view-switcher.tsx) | カード／一覧／締切順の切替。ハイライトは遷移中だけ押した側へ先行し、それ以外はURLに従う |
| [`frontend/lib/motion.ts`](./frontend/lib/motion.ts) | 一覧項目の登場順（`--stagger`）。上限を超えた項目は同じ遅延にまとめる |
| [`frontend/app/globals.css`](./frontend/app/globals.css) | 緩急と時間のトークン（`--ease-settle` / `--dur-*`）、登場アニメーション、`prefers-reduced-motion` での無効化 |

`app/page.tsx` は結果ブロックに検索条件由来の `key` を渡します。同じ画面のURLだけが変わる遷移ではDOMが再利用されるため、これが無いと新しい結果が動きなく差し替わります。

### 2.4 一覧画面のスクロール

PC幅（921px以上）の一覧画面には独立したスクローラーが2つあります。結果側はページ本体のスクロールをそのまま使い、絞り込みパネルだけが自分の内側をスクロールします。

- `.filter-panel` は `--discovery-bar-h` の分だけ下げた位置に `position: sticky` で止まり、`max-height` を `100dvh` からその高さ分引いた値に制限する。パネルは結果より高くなりうるので、これが無いと下端が画面外に固定され、ページを最後までスクロールしても届かない。
- `overscroll-behavior: contain` で、絞り込みの上のホイールは末尾に達してもページへ伝播させない。結果の上のホイールはページだけを動かす。
- `--discovery-bar-h` は sticky bar の高さの正本で、`.discovery-inner` の `min-height` とパネルの停止位置の両方が読む。片方だけ変えるとパネルがbarの裏に潜る。
- 920px以下ではこの列ごと隠れ、絞り込みは `.filter-sheet`（bottom sheet）に移る。スクロールを閉じ込める役割は `.filter-sheet-body` が持つ。
- 絞り込みの開閉で高さが変わったときの位置補正（`components/filter-panel.tsx`）は、行を含むスクローラー側を動かす。パネルもシートも自前のスクローラーなので、windowを動かすと画面が跳ねる。

### 2.5 ブラウザ内データ

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
| `GET /api/v1/companies` | `backend/app/api/companies.py` | 内部トークン | index対象企業（一言説明と本文あり）の一覧 |
| `GET /api/v1/companies/{public_code}` | 同上 | 内部トークン | 公開コードによる企業と、現在／過去の募集 |

RESTの検索はページ番号を返します。既定では公開中かつ東京時間の当日以降が対象で、`q` がある場合は関連度、ない場合は締切順が基本です。MCPの検索は同じドメインサービスを使い、条件シグネチャとスナップショットを含む opaque cursor を返します。

### 3.3 MCP

[`backend/app/mcp_server.py`](./backend/app/mcp_server.py) はツールのスキーマ、`title`、annotations、output schema、認証要否、DBセッション境界を定義します。

| ツール群 | 主な処理 | 認証 |
| --- | --- | --- |
| 検索・詳細・マスタ | `search_opportunity`, `get_opportunity`, `get_master_values`, `get_sectors` | 不要（OAuth有効時の匿名公開にも対応）。募集検索は登録・最終編集日時の両端を含む範囲指定ができる |
| 重複・企業同一性・プロフィール | `find_similar_opportunities`, `find_opportunities_by_source_url`, `resolve_company`, `add_company_alias`, `set_company_industries`, `update_company_profile`, `list_companies_missing_profile`, `list_company_profile_history`, `merge_company`, `get_company_maintenance_context` | 前者2つは不要。企業の候補確認、プロフィール欠落一覧、プロフィール履歴、保守コンテキストと書き込みは認証が必要 |
| 募集書き込み | `validate_opportunity`, `add_opportunity`, `upsert_opportunity`, `upsert_opportunities`, `update_opportunity`, patch/status/verify、`verify_opportunities` | 必要 |
| 削除・履歴 | delete preview/delete/restore/recent writes | 必要 |
| 収集キュー | target/source/check の一覧、確認状況フィルター、未監視企業の検出、キュー、追加、更新、確認記録 | 必要 |
| OAuth接続管理 | `backend/app/scripts/mcp_connections.py` | サーバー上の運用コマンド |

詳細取得の `get_opportunity` は `reference` または互換引数 `opportunity_id` を受け取り、両方の値が異なる場合は拒否します。書き込みツールは、入力を [`backend/app/schemas.py`](./backend/app/schemas.py) で検証し、ドメインエラーを構造化して返します。事前検証の合格応答は未保存を明示します。実際の保存や整合性処理は `mcp_server.py` に複製せず `backend/app/services/` へ委譲します。

### 3.4 ドメインサービス

募集の一括登録・確認は `upsert_opportunities` / `verify_opportunities` で最大50件を受け取り、単件と同じ処理で各件を個別保存する。応答は本文を省いた個別結果と新規登録・既存返却・確認・再試行・拒否・結果未確認の集計で、部分失敗時も成功分を保持する。新規登録と確認は別の入口のままにする（ADR-0029）。

企業プロフィールの一括更新は `update_company_profiles` で最大50社を受け取り、各社を既存のプロフィール更新サービスで個別に検証・保存する。各社の更新日時を照合し、冪等記録と監査ログを保持する。応答は保存成功・拒否・結果未確認の個別結果と集計で、本文の全文は再送しない（ADR-0025）。

| ファイル | 責務 |
| --- | --- |
| `services/opportunities.py` | 検索、登録・最終編集日時フィルターと条件付きカーソル、関連度、固定値解決、重複検出、書き込み、論理削除・復元、監査、MCP保守キューの対象状態判定 |
| `services/companies.py` | 企業名の正規化、正式名・別名の完全一致、候補提示、公開コードの発行と解決、プロフィール欠落の検索、プロフィール変更履歴の読み取り、別名・複数カテゴリ・プロフィールの冪等書き込み |
| `services/company_pages.py` | 企業ページの読み取り。現在／過去の募集の分割、index対象企業の一覧と現行募集件数の集計 |
| `services/company_industries.py` | 企業と複数業界・業種の分類を維持 |
| `services/collection_targets.py` | 企業単位の収集対象、情報源、確認履歴、導出される確認状況の絞り込み、優先度・次回確認日 |
| `services/maintenance.py` | 収集対象の確認期限の共通判定、確認不能・要確認の連続回数と再確認間隔 |
| `services/masters.py` / `master_cache.py` | 固定値の解決とキャッシュ |
| `services/normalization.py` | 企業名、タグ、一次情報URLの正規化 |
| `services/oauth.py` | OAuth client、PKCE認可コード、access/refresh token、grant失効 |
| `services/rate_limit.py` | Redisの固定窓レート制限。OAuthログイン・動的登録などを保護 |
| `services/write_history.py` | 実行ID・クライアント・対象種類による監査履歴の絞り込み、ページング、全該当記録の成功・拒否・結果未確認件数 |
| `services/serialization.py` | DBモデルからREST/MCP/画面共通のレスポンスへ変換。公開詳細URLも生成 |
| `services/errors.py` | 固定値・入力エラーの共通メッセージ |

### 3.5 共通基盤と運用スクリプト

| ファイル | 責務 |
| --- | --- |
| `app/config.py` | 環境変数、URL由来の issuer/resource、production時の開発用秘密値拒否 |
| `app/db.py` | SQLAlchemy engine、session、Declarative Base、トランザクション境界 |
| `app/audit_context.py` | MCP呼び出しごとの実行IDをContextVarで保持し、ネスト・例外・同時呼び出しから分離する共通基盤 |
| `app/schemas.py` | REST/MCPのPydantic入力・出力、固定値型、入力制約 |
| `app/security.py` | 内部token、Bearer、operator password の比較とOAuth token hash |
| `app/master_data.py` | 新規DBへ固定値マスタを投入する定義 |
| `app/dates.py` | 東京時間を基準にした当日判定 |
| `app/scripts/close_expired.py` | 論理削除から30日経過し、再送防止記録のアーカイブが済んだ募集を完全削除（期限超過だけでは状態・公開を変えない） |
| `app/scripts/seed_demo.py` | 架空のUI確認用データを冪等的に投入 |
| `app/scripts/mcp_connections.py` | OAuth grant の一覧・失効・期限切れ掃除 |
| `services/history_archive.py` / `app/scripts/archive_history.py` | 90日より前の履歴・再送防止記録・不要なOAuth tokenをJSONL gzipへ移し、保存検証後にDB行を削除 |
| `.github/workflows/maintenance.yml` | 論理削除30日後の完全削除、履歴アーカイブ、OAuth認可コード掃除を日次実行し、完了markerを監視 |

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
- `companies.public_code` も同じ8文字のCrockford base32で、企業ページのcanonical URLに使う。内部の整数IDは公開URLに出さない。
- `Industry`、`Sector`、職種、卒業年、学位、募集状況、イベント種別、形式は固定値マスタ。募集書き込み時は指定業界に属する業種だけを受け付ける。
- 企業同一性は正規化正式名または明示登録した別名の完全一致を正本にする。部分一致・`pg_trgm` は候補提示と検索補助だけで、企業を自動統合しない。
- 企業は複数業界に属せる。`company_industries.is_primary` は1社につき高々1件で、単一分類表示用である。
- 企業プロフィールは `companies.business_summary`（1〜2文の一言説明）、`description`（300文字以上の本文）、`business_areas`（主な事業のJSON配列）、`website_url` の4項目で、運営者がMCPの `update_company_profile` だけで書く。各項目には最小文字数があり、一言だけの登録は入力検証で拒否する。省略した項目は維持し、`null` の明示だけが削除である。`business_areas` だけは指定内容で全置換する。確認した公式ページは列ではなく監査ログの `source_url` に残す。企業統合では統合先のプロフィールを優先し、統合先が未登録の項目だけ統合元から引き継ぐ。
- `set_company_industries` は既存企業の業界・業種カテゴリを指定一覧で全置換する。カテゴリは1件以上、現在の業界マスタ数まで指定でき、先頭を `is_primary` として監査・冪等化する。
- `source_url` は正規化した `normalized_source_url` と共に保存する。短縮URL、IP/localhost、求人集約・口コミサイトを情報源として拒否し、同じ一次情報URLは登録拒否ではなく確認用警告とする。収集対象がある企業では、有効な `collection_sources` を企業別公式source allowlistとし、別の公式ホストは収集元へ明示登録してから使う。

### 4.2 企業単位の収集

```text
companies ──1:1── collection_targets ──< collection_sources
                                  └──────< collection_checks ──?── opportunities
```

- `collection_targets` は1企業につき1件。複数業界の分類は `company_industries` に置き、同じ企業を二重巡回・二重計上しない。
- 企業カテゴリの直接設定は収集対象の作成を必要としない。`resolve_company` で確認した `company_id` に対して `set_company_industries` を使い、収集対象を後から追加できる。
- `list_unmonitored_companies` はCompanyを起点に、収集対象がない企業を返す。`add_collection_target` は既存CompanyのIDを明示指定でき、名前の再入力による重複Company作成を防ぐ。
- `collection_targets.is_active` と各 source の `is_active` は無効化で保持する。削除ではなく運用状態を表す。
- `list_undercovered_companies` は通常収集キューと同じ確認期限を取得上限前に適用する。`unreachable`・`needs_review` の連続回数を `consecutive_failed_checks` に持ち、初回は通常間隔、以後は倍増し、90日または元の間隔の大きい方で頭打ちにする。`found`・`no_opening` で通常間隔へ戻す（ADR-0027）。
- 募集の新規登録（`add_opportunity`／`upsert_opportunity`）へ正しい `collection_target_id` を渡すと、募集保存と `found` 確認記録を同じトランザクションで作る。IDを省略した場合も企業一致で自動リンクできる。既存募集の更新・部分更新はこの自動リンクを行わない（4.3参照）。
- 採用ページ未登録、未確認、確認期限超過は収集キューの状態として返される。
- `record_collection_check` は実際に確認したURLを必須とする。`found` は募集自身の一次情報URLとの一致、その他の結果は登録済み有効sourceとの一致を検証し、一致した `found` だけが募集の `source_checked_at` を進める。
- `list_stale_opportunities(exclude_expired=true)` は、東京時間の当日より前の締め切り・実施終了日を持つ募集をSQLの件数制限前に除外する。当日・日付未設定は残し、既定のfalseは日付と「募集中」の矛盾を優先する（ADR-0026）。
- 日付矛盾がある募集を明示的に再確認すると `date_status_reviewed_at` を記録し、`days`（既定7日）経過まで同じ矛盾を再取得しない。募集状況・締め切り・実施終了日・一次情報URL・企業の変更と復元はこの記録を解除する。本文やタグの編集は維持し、内容更新だけでは一次情報確認日時を進めない（ADR-0027）。
- 定期再確認の対象状態は `募集予定`、`募集中`、`通年募集` に限る。 `締切` などの終了状態は企業保守コンテキスト、収集対象の募集一覧、要確認キューから除外する。企業単位の収集キューは、新しい募集の発見が必要な企業を拾うため、現在の募集一覧が空でも返す。

### 4.3 書き込みの安全性

- `request_id` と payload hash を `idempotency_records`、企業別名・企業統合を `company_request_records`、収集操作を `collection_request_records` に記録する。同じID・同じ内容の再試行は前回結果を返し、内容や対象が違えば拒否する。
- 監査・確認履歴と再送防止記録はDBに90日保持し、古い全列を専用永続ボリュームへ圧縮して移す。再送保証は90日で、古いIDは再実行される場合がある。MCP履歴の一覧・件数はDB内の記録のみを対象とし、`retention_days` を返す。ファイルの永続化・読戻し検証後だけDB行を削除する（ADR-0028）。
- 企業統合は明示した統合元IDの募集、別名、業界分類、収集対象・情報源・確認履歴を統合先へ移し、統合元のCompanyを物理削除する。監査ログは不変の履歴として旧IDを保持する。名前の類似だけで自動統合しない。
- 成功・失敗を `audit_logs` に記録する。全MCP書き込みは任意のトップレベル `run_id` を受け付け、共通例外境界の実行スコープ内で挿入される監査ログへ付与する。実行IDは冪等性の判定に影響せず、処理済み再試行で元の監査記録を書き換えない。`list_recent_writes` は実行IDで絞り込み、ページングと全該当記録数を返す。成功・拒否・結果未確認は監査記録の分類であり、企業数・募集数・ツール呼び出し数ではない。内部エラーとして記録された結果未確認は拒否と区別し、履歴のない通信失敗等の結果は集計から確定しない（ADR-0026）。`verify_opportunity` は内容更新・status更新とは別の `verify` 操作として、確認時刻と実際に確認した一次情報URLを記録し、`updated_at` は変えない。現状は閲覧画面や自動ロールバックを持たないため、運用確認は MCP の履歴ツールまたはDBで行う。
- 書き込みと一次情報確認は分離している（write != verify）。`update_opportunity`／`patch_opportunity` によるDB内容の変更は `source_checked_at` を更新せず、`collection_target_id` も受け付けない。一次情報を確認した事実は `verify_opportunity` または `record_collection_check` で別途記録する。`source_checked_at` が更新されるのは新規登録時と、この2ツールによる確認記録時だけである。
- 日付と募集状況の矛盾（例: 未来の締め切りで「締切」）は、書き込みを拒否せず `warnings` として返す。締切延長・追加募集・中止の可能性があるため、運営者が一次情報を確認して確定する。
- 全項目更新・部分更新・募集状況更新・削除はいずれも `expected_updated_at`（`get_opportunity` で取得した現在の `updated_at`）を必須にし、`FOR UPDATE` 相当のロック取得後に一致を確認して楽観ロックする。取得後に別クライアントが更新していれば拒否し、lost update を防ぐ。
- 削除はまず `deleted_at` を設定する論理削除。通常の検索・詳細から隠し、復元時は同じUUID・公開コードを維持する。論理削除から30日後に日次ジョブで完全削除する。ただし再送防止記録が残る募集は、90日経過後に記録のアーカイブが完了するまで保持する。期限・実施終了日が過去なのに「募集中」の矛盾は、`list_stale_opportunities` が最優先の要確認として返すが、自動では状態変更・削除しない。完全削除時は収集確認履歴の募集参照を解除し、監査ログは保持する。 `締切` などの終了状態は定期再確認キューへ戻さない。
- 重複判定は同一企業・同名イベントだけでなく、対象卒業年・実施開始日・対象職種を識別キーとして`classify_duplicate_candidates`が exact／probable の2段階に分ける。3項目のいずれかが明確に異なれば probable とし、書き込みは拒否せず警告で知らせる（例: 同じイベント名を複数の卒業年で使い回す企業）。全項目が一致する exact 重複だけを既定で拒否し、意図的に同じ内容を複数登録する場合だけ `allow_duplicate` を明示する。復元も同じ分類器を使い、exactだけを拒否する。

### 4.4 OAuthデータ

`oauth_clients`、`oauth_authorization_codes`、`oauth_tokens` が OAuth の状態を保持します。認可コードはPKCE必須、tokenはハッシュのみ保存、refresh token の再利用は grant 全体を失効させます。接続は `mcp_connections` スクリプトで一覧・失効・期限切れ掃除を行います。

認可コードの期限切れ掃除は日次実行する。期限切れaccess tokenと有効tokenを持たないgrantの不要tokenは90日経過後にアーカイブへ移す。有効grantの使用済みrefresh tokenは再利用検知のためDBに保持する。

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
- `20260919_0015_repair_normalization_and_add_indexes.py` は、正規化ルールの変更に追随していなかった `companies.normalized_name` / `company_aliases.normalized_alias` を現行ルールで再計算し、`collection_checks` から `last_check_result` を再導出し、ダングリングな `collection_request_records` を整理したうえで、`models.py` が先行して持っていた索引を追加する。正規化の再計算で一意制約に衝突する行は修復せず据え置き、WARNING で対象グループを名指しする（例外で停止すると `alembic upgrade head && uvicorn` の起動が止まるため）。名指しされた行は `merge_company` で手動解消してから再実行する。

- `20261004_0016_add_audit_run_id.py` は `audit_logs.run_id` と索引を追加する。既存記録はNULLのまま保持し、新規DBではORMが作成済みの列・索引をスキップする。
- `20261005_0017_add_maintenance_review_schedule.py` は日付矛盾の再確認日時と連続確認不能回数を追加する。既存行はNULL／0を設定し、過去の確認の意味を補完しない。新規DBでは作成済みの列をスキップする。

スキーマを変更するときは ORM、migration、fresh DB、既存DB upgrade、必要な回帰テストを一緒に確認します。

### 6.2 Composeと公開境界

| 構成要素 | 定義 | 役割 |
| --- | --- | --- |
| `db` | `docker-compose.yml` | PostgreSQL 16、永続 volume `postgres_data` |
| `redis` | `docker-compose.yml` | Redis 7、レート制限、永続 volume `redis_data` |
| `api` | `backend/Dockerfile` | Alembic後に Uvicorn/FastAPI を8000番で起動 |
| `frontend` | `frontend/Dockerfile` | Next standalone を3000番で起動 |
| Nginx | `relua.conf` | TLS、`www`からapexへの308、公開MCP/OAuth、Next.jsへのルーティング、MCPストリーミングの非バッファリング |

環境変数の一覧と開発値は [`.env.example`](./.env.example)、起動手順は [`docs/usage.md`](./docs/usage.md) を正本とします。実際の秘密値は `.env` に置き、コミットしません。

### 6.3 CI/CD

[`.github/workflows/ci.yml`](./.github/workflows/ci.yml) の正本は次の3段階です。

- backend: Ruff、SQLite単体テスト、PostgreSQL Alembic upgrade、`pg_trgm`／関連度の確認。
- frontend: `npm ci`、lint、`tsc --noEmit`、Vitest、production build。
- main push: SSH先で `docker compose up -d --build`、サービス状態を確認し、失敗時は直前コミットへ戻して再起動する。
- daily schedule: SSH先で履歴アーカイブ、論理削除済み募集の完全削除、OAuth認可コード掃除を順に実行し、終了コードと `archived_audit=<件数> archived_checks=<件数>` / `purged=<件数>` / `purged_authorization_codes=<件数>` markerを個別に検証する。

## 7. 変更時のソースマップ

| 変更したいもの | 最初に読むコード | 同時に確認するもの |
| --- | --- | --- |
| 公開一覧・詳細 | `frontend/app/`, `frontend/components/`, `frontend/lib/api.ts` | `backend/app/api/opportunities.py`, frontend tests |
| 企業ページ・企業プロフィール | `frontend/app/companies/page.tsx`, `frontend/app/companies/[code]/page.tsx`, `backend/app/services/company_pages.py`, `backend/app/api/companies.py` | `services/companies.py` の `update_company_profile`, `test_company_pages.py`, ADR-0017, ADR-0023 |
| canonical・index対象 | `frontend/proxy.ts`, `frontend/lib/site.ts`, `frontend/lib/seo.ts`, `frontend/lib/seo-data.ts`, `frontend/lib/sitemap.ts`, `frontend/app/sitemap.xml/route.ts`, `frontend/app/sitemaps/[page]/route.ts` | `relua.conf`, SEO/sitemap tests、ADR-0016、ADR-0018、ADR-0022 |
| 起動時の必須設定・信頼するプロキシ | `backend/app/config.py`, `docker-compose.yml`, `frontend/lib/site.ts`, `frontend/lib/api.ts` | `.env.example`, `relua.conf`, `test_security.py`, `test_rate_limit.py`、ADR-0019 |
| 保存・共有・QR | `frontend/lib/local-data.ts`, `components/saved-dashboard.tsx` | `backend/app/services/serialization.py`, local-data/UI tests |
| RESTのレスポンス | `backend/app/api/`, `schemas.py`, `services/serialization.py` | `frontend/lib/types.ts`, API呼び出し、認証ヘッダー |
| 検索・重複・書き込み | `backend/app/services/opportunities.py` | `schemas.py`, `mcp_server.py`, `test_opportunities.py`, `test_mcp_tools.py`。日時フィルターはカーソル条件にも含める。一括登録・確認は単件処理を再利用し、結果と実績を区別する（ADR-0029） |
| 企業同一性・プロフィール更新・履歴 | `services/companies.py`, `company_industries.py` | `schemas.py`, `mcp_server.py`, `test_companies.py`, `test_mcp_tools.py`、`models.py` の `AuditLog`、関連ADR。一括更新は企業ごとの検証・更新日時照合・保存・結果集計 |
| 収集キュー・再確認間隔 | `services/collection_targets.py`, `services/maintenance.py` | `models.py`, `test_collection_targets.py`, `test_mcp_tools.py`, `test_maintenance_schedule_migration.py`, MCP tool definitions。無効な確認URL・重複追加のエラーは既存の情報源IDと状態を返す。確認状況は履歴列から導出し、確認期限と連続回数で巡回を制御する |
| 実行単位の書き込み履歴 | `services/write_history.py`, `app/audit_context.py`, `models.py` の `AuditLog` | `mcp_server.py`, `schemas.py`, `test_mcp_tools.py`, `test_audit_context.py`, `test_audit_run_migration.py`、ADR-0026 |
| OAuth・MCP認証 | `main.py`, `api/oauth.py`, `services/oauth.py`, `mcp_server.py` | `test_oauth.py`, `test_oauth_endpoints.py`, `relua.conf` |
| 共通基盤・運用ジョブ | `config.py`, `db.py`, `schemas.py`, `security.py`, `dates.py`, `scripts/` | `.env.example`, Compose、`.github/workflows/maintenance.yml`、該当サービスのテスト |
| 履歴保存・再送保証 | `services/history_archive.py`, `app/scripts/archive_history.py` | `test_history_archive.py`, `config.py`, `.env.example`, Composeの永続ボリューム、MCP履歴契約、ADR-0028 |
| DBスキーマ | `models.py`, 最新 migration | 0001 fresh DB、全 upgrade、PostgreSQL CI |
| デプロイ・公開境界 | `docker-compose.yml`, Dockerfiles, `relua.conf`, CI | `.env.example`, `docs/usage.md` の本番設定 |

## 8. ドキュメントの使い分け

- 構造を探すときはこの文書。
- コマンドや運用手順を実行するときは [`docs/usage.md`](./docs/usage.md)。
- コードを変更する前の規約（構成、コマンド、同期すべきもの、命名、テスト方針）は [`docs/knowledge/development_conventions.md`](./docs/knowledge/development_conventions.md)。
- 利用者、利用の流れ、用語の対応、状態を確認するときは [`docs/knowledge/domain_glossary.md`](./docs/knowledge/domain_glossary.md)。
- 契約やマイグレーションを変えるときは [`docs/knowledge/contracts-and-migrations.md`](./docs/knowledge/contracts-and-migrations.md)。
- 同じ問題を再現・切り分けるときは [`docs/knowledge/debugging.md`](./docs/knowledge/debugging.md)。
- 設計を変えるか迷ったときは [`docs/decisions/README.md`](./docs/decisions/README.md) と関連ADR。

新しい文書は、既存文書に書かれた事実を転載するのではなく、責務・理由・再利用可能性のいずれかを補う場合だけ追加します。
