# 開発規約

コードを変更する作業では、着手前にこの文書を読みます。用語と状態は [`domain_glossary.md`](./domain_glossary.md)、構造の説明は [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)、切り分け手順は [`debugging.md`](./debugging.md)、判断の理由は [`../decisions/README.md`](../decisions/README.md) にあり、ここには「どう作業するか」だけを書きます。

## 1. プロジェクト構成

| 領域 | 場所 | 中身 |
| --- | --- | --- |
| フロントエンド | `frontend/app/`、`frontend/components/`、`frontend/lib/` | Next.js App Router。`app/` はルートと metadata、`components/` は画面部品、`lib/` は server-only の API クライアント、SEO データ、ブラウザ内保存、整形関数 |
| スタイル | `frontend/app/globals.css` | 唯一のスタイルシート。方針は [`../../frontend/STYLING_STRATEGY.md`](../../frontend/STYLING_STRATEGY.md) |
| バックエンド入口 | `backend/app/main.py`、`backend/app/api/`、`backend/app/mcp_server.py` | 認証ミドルウェア、内部 REST、OAuth、MCP ツール定義 |
| ドメイン | `backend/app/services/` | 検索・書き込み・企業同一性・収集キュー・OAuth・レート制限。ツールや API から呼ぶ本体 |
| スキーマ | `backend/app/models.py`、`backend/app/schemas.py`、`backend/alembic/versions/` | ORM、入出力の Pydantic モデル、マイグレーション |
| 共通基盤 | `backend/app/config.py`、`db.py`、`security.py`、`dates.py`、`master_data.py`、`backend/app/scripts/` | 設定、接続、認証補助、東京時間の日付、固定値マスタ、運用コマンド |
| テスト | `backend/tests/`、`frontend/**/*.test.ts(x)` | backend は pytest、frontend は Vitest（テストは実装ファイルの隣に置く） |
| 検証スクリプト | `scripts/` | ドキュメントのパス参照と環境変数の整合を CI で検証する |

## 2. ビルド・テストコマンド

Backend は Python 3.12 が正本です（`backend/Dockerfile`、CI）。ローカルに 3.12 の仮想環境がある場合は `backend/.venv/bin/pytest` のようにそれを使います。Frontend は Node 24 です。

```bash
# backend
cd backend
pip install -r requirements-dev.txt
DATABASE_URL=sqlite:// pytest                 # SQLite の単体テスト
DATABASE_URL=sqlite:// pytest tests/test_mcp_tools.py -k duplicate   # 対象を絞る
ruff check .

# frontend
cd frontend
npm ci
npm test                                       # vitest run
npx vitest run lib/seo-data.test.ts            # 対象を絞る
npm run lint
npm run typecheck                              # eslint も vitest も型検査をしないため必須
NEXT_PUBLIC_SITE_URL=http://localhost:3100 npm run build

# docs / env
python3 scripts/check_doc_paths.py
python3 scripts/check_env_documentation.py

# 起動（リポジトリ直下に .env が必要）
cp .env.example .env    # 初回のみ
docker compose up --build
docker compose exec api python -m app.scripts.seed_demo   # UI 確認用の架空データ
```

PostgreSQL 固有の確認（Alembic の `upgrade head`、`pg_trgm`、関連度検索、`FOR UPDATE`）は CI の backend ジョブか、Compose の `db` に対して行います。SQLite で通ったことだけを根拠に PostgreSQL 経路を確認済みとしません。

## 3. スキーマと契約の同期

1 つの変更で一緒に更新するものを固定します。詳細は [`contracts-and-migrations.md`](./contracts-and-migrations.md) にあります。

| 変えるもの | 同時に更新するもの |
| --- | --- |
| `models.py` | 新しい migration、`ARCHITECTURE.md` §4／§6.1、対象サービスのテスト |
| REST のレスポンス（`schemas.py`、`services/serialization.py`） | `frontend/lib/types.ts`、frontend の呼び出し側、`README.md` の「内部REST API」 |
| MCP ツールの名前・引数・説明・認証要否 | `backend/tests/test_mcp_tools.py`、`README.md` の「MCPツール」表 |
| 環境変数 | `.env.example`、`docker-compose.yml`、`frontend/Dockerfile`（`NEXT_PUBLIC_*` の場合）、`README.md` の「本番公開前の設定」 |
| 公開 URL・index 条件 | `frontend/lib/seo.ts`、`frontend/proxy.ts`、サイトマップ、`relua.conf`、関連 ADR、[`seo-debugging.md`](./seo-debugging.md) |
| 固定値マスタ（業界・業種・種別など） | `master_data.py` と投入 migration、`README.md`、SEO allowlist（index 対象に影響する場合） |

## 4. 実装規約

### 共通

- 日付は `backend/app/dates.py` の関数で扱います。tz-aware な値から日付だけを切り出すと JST 00:00〜09:00 の記録が前日になり、`date.replace(year=...)` は閏日で例外になります。どちらも実際に起きた不具合です。
- 部分一致検索に渡す文字列は `%`／`_` をエスケープします（`?q=%` が全件一致していたことがあります）。
- 既存行を更新・削除・復元する経路は `expected_updated_at` による楽観ロックと行ロック（`FOR UPDATE`）を通します（ADR-0002）。`joinedload` と `with_for_update()` を組み合わせるときは `of=` で対象テーブルを限定します。PostgreSQL は外部結合の nullable 側に `FOR UPDATE` を掛けられず、SQLite では気づけません。
- 書き込み系の操作は `request_id` で冪等化し、監査ログに残します。再試行は同じ `request_id`、内容を直した再送は新しい `request_id` です。
- DB の内容を変える操作と、一次情報を確認した事実を記録する操作は分けます（ADR-0010）。内容の編集で `source_checked_at` を進めません。
- 設定は fail-closed にします。既定値で安全側へ倒れる設計（未設定なら拒否、未知の値なら起動失敗）を保ち、「本番のときだけ厳しくする」条件分岐を追加しません（ADR-0019）。
- 例外メッセージや検証エラーに SQL、バインド値、内部パスを含めません。MCP ツールは登録時の共通例外境界（ADR-0020）に任せ、ツールごとに `try/except` を書きません。
- レート制限やロックの全体カウンタ（アドレスに依らない共有上限）は、攻撃者が回すだけで運営者を締め出せるため使いません。解決できた IP ごとに数えます。

### Backend

- Ruff の設定は `backend/pyproject.toml`（`E`、`F`、`I`、`B`、`UP`、行長 120）です。import 順は Ruff に任せます。
- 入出力は `schemas.py` の Pydantic モデルで検証し、日本語の項目名は `services/errors.py` の `FIELD_LABELS` に追加します。項目名を返すエラーはここを経由します。
- ドメイン処理は `services/` に置き、`api/` と `mcp_server.py` は入出力の変換と認可だけを担当します。
- 企業の同一視は正規化名の一致か明示登録した別名だけで行い、部分一致や trigram の候補は「確認用」に返すだけで統合の根拠にしません（ADR-0004、ADR-0011）。業種の解決は業界でスコープします（同名の「その他」が業界ごとに存在します）。

### Frontend

- `frontend/lib/api.ts` は `server-only` です。ブラウザ側のコードやテストから直接 import しません。
- 公開 origin は `frontend/lib/site.ts` を通して取得し、`process.env.NEXT_PUBLIC_SITE_URL` を直接読みません。
- スタイルは `globals.css` の意味クラスで書き、Tailwind のユーティリティを JSX に並べません。トークンの追加・変更は [`../../frontend/DESIGN_TOKENS.md`](../../frontend/DESIGN_TOKENS.md) の規則に従います。
- SEO データ（`frontend/lib/seo-data.ts`）とサイトマップは API 障害時に 200＋空一覧へ縮退させず 5xx／503 を返します（ADR-0016、ADR-0018）。Data Cache に関わる変更は `next dev` ではなく本番ビルドで確認します。
- 画面遷移中は現在の DOM を保持する構成です。`loading.tsx` の追加、`scroll-behavior: smooth`、ハッシュ遷移の追加は [`debugging.md`](./debugging.md) の該当章を読んでから行います。

## 5. 命名規則

| 対象 | 規則 | 例 |
| --- | --- | --- |
| Alembic migration | `YYYYMMDD_NNNN_<snake_case>.py`。`revision` はファイル名の日付と連番、`down_revision` は現在の唯一の head | `20260919_0015_repair_normalization_and_add_indexes.py` |
| ADR | `NNNN-<kebab-case>.md`。番号は既存の最大値＋1 | `docs/decisions/0023-company-pages-indexed-on-profile-alone.md` |
| backend テスト | `tests/test_<対象モジュールまたは機能>.py`。関数は `test_<振る舞い>` | `test_mcp_tools.py::test_update_opportunity_requires_expected_updated_at_and_rejects_stale_writes` |
| frontend テスト | 実装ファイルの隣に `<name>.test.ts(x)` | `lib/seo-data.test.ts`、`components/view-switcher.test.tsx` |
| CSS クラス | 役割を表す意味クラス（kebab-case）。状態は修飾クラスで表す | `.discovery-bar`、`.filter-summary-compact` |
| MCP ツール | `動詞_対象` の snake_case。読み取りは `get_`／`search_`／`find_`／`list_`、書き込みは `add_`／`update_`／`patch_`／`delete_`／`restore_`／`merge_` | `update_company_profile` |
| 環境変数 | `UPPER_SNAKE_CASE`。ブラウザへ露出するものだけ `NEXT_PUBLIC_` 接頭辞 | `API_INTERNAL_TOKEN`、`NEXT_PUBLIC_SITE_URL` |
| ブランチ | `<種類>/<kebab-case>` | `fix/seo-snapshot-blocking-refresh` |

## 6. 責務分割

- Next.js は公開 BFF です。ブラウザから FastAPI へ直接は到達させず、`frontend/lib/api.ts` が内部トークン付きで呼びます（ADR-0001）。
- FastAPI の REST は内部専用、MCP と OAuth だけが `relua.conf` で公開されます。公開面を増やす変更は ADR を伴います。
- 書き込みの唯一の入口は MCP です。REST と公開画面からは書きません。
- ブラウザ内保存（ブックマーク、引き継ぎ）はサーバーに持たず、公開コードで共有します（ADR-0003）。
- 運用ジョブ（完全削除、MCP 接続の管理、デモ投入）は `backend/app/scripts/` に置き、GitHub Actions から SSH で実行します。アプリのリクエスト処理に混ぜません。

### ドメインの境界と業務ルールの置き場所

用語・同一性・状態の対応は [`domain_glossary.md`](./domain_glossary.md) にあります。

- 層は「入口（`api/`、`mcp_server.py`、Next.js の `app/`・`components/`）→ ドメイン（`services/`、`frontend/lib/` の純粋関数）→ 保存・外部（`models.py`、Redis、FastAPI への呼び出し）」の順に依存させ、逆向きに呼びません。
- ドメインの境界は `services/` のモジュール単位です（募集、企業、企業分類、企業ページ、収集対象、固定値、OAuth）。新しい関心事は、境界を名指しできるなら既存モジュールに足さず別モジュールにします。すでに大きい `services/opportunities.py` と `mcp_server.py` に、募集や MCP の入口と関係のない責務を足しません。
- 業務ルール（書き込み可否、同一企業の判定、重複判定、再確認の対象、日付と募集状況の矛盾、index 条件）はドメインの関数に 1 か所だけ置き、入口の if 文で書き直しません。frontend の判定（index 可否、保存データの検証）も `frontend/lib/` の純粋関数に置き、コンポーネントは結果を表示するだけにします。
- 現在のコードには、同じ業務ルールが backend と frontend などに重複している箇所があります。変えるときはすべてを同じ変更で直し、片方だけ直して済ませません。
  - 企業ページの index 条件: `services/company_pages.py` の `_profile_is_complete` と `frontend/lib/seo.ts` の `companyIsIndexable`
  - 現行募集とみなす募集状況: `services/opportunities.py` の `RECONFIRMABLE_RECRUITMENT_STATUSES`、`api/opportunities.py` の類似募集取得に直書きした一覧、`frontend/lib/seo.ts` の `INDEXABLE_OPPORTUNITY_STATUS_SLUGS`
- 状態を増やす、または遷移に制約を加えるときは、状態の一覧と遷移を先に書き出して合意し、ADR に残します。現在の状態と、システムが強制している範囲は [`domain_glossary.md`](./domain_glossary.md) の「状態」にあります。
- 外部との接点は専用のモジュールを 1 つ挟みます。Redis は `services/rate_limit.py` と `services/master_cache.py`、FastAPI への呼び出しと内部 API の接続設定（`API_INTERNAL_*`）は `frontend/lib/api.ts`（例外は旧 UUID の転送だけを行う `frontend/proxy.ts`）、ブラウザから BFF への呼び出しは `frontend/lib/browser-api.ts`、backend の設定値は `config.py`、公開 origin は `frontend/lib/site.ts` を通します。新しい外部サービス（メール、外部 API など）を足すときも、仕様をその adapter モジュールの中に閉じ込め、設定を 1 か所に置き、テストでは adapter をモックします。外部サービスの追加は依存関係と公開面の変更なので、ADR と PR 本文での説明を伴います。
- 読み取りと書き込みの要求が大きく違うもの（企業ページ、SEO データ、サイトマップ）は、`services/company_pages.py` のように読み取り専用の関数・モジュールへ分けて構いません。読み取り専用の DB や同期の仕組み（CQRS の基盤）は、単一の PostgreSQL で要件を満たせない根拠が出るまで入れません。
- 履歴は現在の行、監査ログ（`audit_logs`）、冪等記録、確認記録（`collection_checks`）で持ちます。Event Sourcing は現時点では入れず、必要になったら ADR で判断します。監査ログを書き換える経路は作りません。

## 7. テスト方針

- 変更した箇所と直接影響を受ける範囲のテストだけを実行します。全体実行は横断的な変更かユーザーが求めたときだけです。
- 振る舞いを変えたら、その振る舞いを固定するテストを同じ変更で追加します。回帰修正では「壊れていた入力」をそのままテストにします。
- backend のテストは `conftest.py` が SQLite に ORM metadata と固定値を直接作ります。Alembic の経路や PostgreSQL 固有機能は確認されないため、schema・検索・ロックに触る変更は CI の PostgreSQL ジョブか Compose の `db` で追加確認します。SQLite と PostgreSQL で結果が変わることが分かっているテストは、どちらの結果が正本かをテスト内に書きます。
- frontend の `lib/` の純粋関数、ブラウザ保存、SEO 判定は Vitest で固定します。描画に影響する変更は Vitest だけで完了とせず、[`frontend_visual_verification.md`](./frontend_visual_verification.md) の実描画確認を行います。
- テストの中で外部ネットワークへ出ません。API 応答はモックまたは固定値にします。
- 「テストが通った」だけでなく、実行したコマンドと結果（件数、失敗の有無）を PR 本文に書きます。

## 8. サブエージェントの指定

役割ごとに別の担当を使い、各担当にはその役割に必要な情報だけを渡します。
以下のモデル指定は、調査・実装・レビューのいずれでサブエージェントを使う場合にも適用します。
Claude Code のサブエージェントは `sonnet5 high` を指定します。
Codex のサブエージェントは `gpt-6-luna` を指定し、reasoning effort を `max` にします。

| 役割 | 渡すもの | 渡さないもの | Claude Code での指定 | Codex での指定 |
| --- | --- | --- | --- | --- |
| 調査 | 問い、探す範囲、結論の形式 | 実装案 | `Explore` エージェント（読み取りのみ） | 読み取り専用のサブエージェント |
| 実装 | 合意済みスコープ、対象ファイル、規約への参照 | 他担当の途中成果物 | `general-purpose` エージェント | 書き込み可のサブエージェント |
| レビュー | スコープ、差分（`git diff`）、チェックリスト（要件を満たす／スコープ外の変更が無い／不要なコードが無い／テストが通る／禁止事項に触れない） | 実装担当の意図・経緯の説明 | `code-review` スキル、または `general-purpose` エージェントにレビューだけを依頼 | 差分とチェックリストだけを渡した別のサブエージェント |

- レビュー担当の指摘は、実装担当が検証してから反映します。反論がある場合はユーザーに上げ、握りつぶしません。
- ドキュメントだけの変更はレビュー担当を省略でき、省略した場合は PR 本文にその旨を書きます。
- 最終判定はユーザーです。担当間の判断の不一致はユーザーに上げます。

## 9. 過去の障害・手戻りから決めた規約

ここに書くのは、git 履歴に残る実際の不具合から一般化した規約です。個別の修正内容は各 PR と ADR にあります。

| 規約 | 由来 |
| --- | --- |
| migration はデータ品質の問題で例外停止しない。修復できない行は据え置いて WARNING で名指しし、後続の手動対応（`merge_company` など）へ委ねる | 正規化修復 migration が衝突行で `RuntimeError` を投げ、`alembic upgrade head && uvicorn` の起動コマンドが止まって本番全体が 500/502 になった（PR #72） |
| コンテナの healthcheck はアプリ自身に問い合わせる。シェルが起きただけで healthy にしない | migration 失敗で uvicorn が一度も動いていないのに、デプロイが成功扱いになり CI は緑のままだった（PR #72） |
| 後続 migration は「存在するならスキップ」を持つ。新規 DB は `0001` が現行 ORM metadata を `create_all` するため、後続が追加する列・索引を既に持っている | `0003` の `public_code` 追加が新規本番 DB で `DuplicateColumn` になった。seed migration も NOT NULL 列の追加で新規 DB だけ失敗した（PR #21、PR #69） |
| データ投入・修復 migration はアプリと同じ正規化関数を使う。migration 側に独自実装を置かない | seed migration の正規化がアプリと乖離し、4 社が一致しない `normalized_name` で投入されていた（PR #71） |
| 新しい設定はデフォルトで安全側に倒す。「production のときだけ拒否」ではなく「development を明示したときだけ許可」にし、compose は `${VAR:?}` で止める | `ENVIRONMENT` の既定が development で、`.env` のキー名を 1 つ間違えるだけで公開中の `/mcp` が公開済みトークンで開いた（PR #71、ADR-0019） |
| 必須設定を増やす PR は、本文に「デプロイ前にサーバーの `.env` を更新する」と変数名を明記する | fail-closed 化と `ENVIRONMENT` 既定値の変更が同時に入り、サーバー側の `.env` が追随しないと起動しない状態になった（PR #71、PR #72） |
| `NEXT_PUBLIC_*` はビルド時に焼き込まれる。ビルド時にも検証し、Dockerfile の `ARG` に既定値を置かない | 変数なしのビルドが canonical・OGP・JSON-LD すべて localhost の静的ページを生成し、200 を返し続けた（PR #71、ADR-0019） |
| CI では `npm run typecheck` と `npm test` を必ず回す | eslint も vitest も型検査をしないため、実在する TypeScript エラー 2 件が手で `tsc` を叩くまで残っていた（PR #71） |
| Next.js の Data Cache は期限切れを返して背後で更新する前提で設計する。鮮度切れは例外ではなくブロッキング再取得にする | 1 時間以上訪問のない URL の初回だけ 500、リロードで 200 になっていた（PR #70、ADR-0018） |
| SEO データとサイトマップは障害時に 200＋空一覧へ縮退しない | API 障害中に `noindex` や空一覧の 200 が返り、index が消えた（PR #66、PR #68、ADR-0016） |
| index 可否を在庫の件数で決めない。プロフィールや allowlist のような安定した条件だけにする | 募集件数で index／`noindex` を往復し、募集期ごとに評価が揺れた（PR #73、ADR-0023） |
| 既存行の更新経路はすべて `expected_updated_at` を必須にする。決定に漏れがあれば ADR 側を直す | `update_opportunity` だけが楽観ロックを取っておらず、古い読み取りからの上書きが通っていた（PR #57） |
| PostgreSQL 実機で回帰確認する。特に `FOR UPDATE`、`pg_trgm`、GIN 索引 | `joinedload`＋`with_for_update()` が PostgreSQL で `FOR UPDATE cannot be applied to the nullable side of an outer join` になり、既存レコードの更新・削除・復元が全滅した。SQLite のテストは通っていた（PR #71） |
| 内容の編集と一次情報の確認を別の操作にする | すべての書き込みが `source_checked_at` を進め、タグ修正が「公式情報を今確認した」記録になっていた（PR #57、ADR-0010） |
| 収集対象は 1 社 1 対象。企業の業界分類は多対多で持つ | 業界ごとに対象が分かれ、同じ企業が二重に確認・集計されていた（PR #50、ADR-0004） |
| 固定値の解決は親（業界）でスコープする | 業界ごとに存在する「その他」が全体一致で解決され、正しい組み合わせが不一致として拒否された（PR #49） |
| 例外境界を公開面に置き、内部エラーの本文を返さない | 37 ツールに例外処理が無く、未認証で叩けるツールから SQL 全文とバインド値が返った（PR #71、ADR-0020） |
| レート制限に全体カウンタを使わない。プロキシ配下では `FORWARDED_ALLOW_IPS` を実際の直前ホップに合わせる | クライアント IP が全リクエストで同一になり、誤パスワード数回で運営者をロックアウトできた（PR #71） |
| 日付は `dates.py` を通す | 締切の相対表示ずれ、JST 早朝の前日表示、閏日の `ValueError` が別々の時期に起きた（PR #42、PR #71） |
| 見た目に触る変更は実機幅（スマホ幅と PC 幅）でスクリーンショットを目視する | ブラウザ確認でフッターが固定バーの裏に隠れる、チップが切り取られるなどの欠陥が見つかり、一度 revert して作り直した（PR #8） |
| CI の concurrency 設定を変えるときは `main` の Deploy が打ち切られないかを確認する | 連続マージで直前の Deploy が打ち切られる経路がある。詳細は `.github/BRANCH_PROTECTION.md` |
| 日次ジョブは完了 marker（`purged=<件数>`）を検証し、失敗通知を有効にする | 論理削除の完全削除を「動いているはず」で放置しないための設計（PR #59、ADR-0014） |
