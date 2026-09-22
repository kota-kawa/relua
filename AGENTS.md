# リポジトリガイドライン

このリポジトリで作業するエージェント（Codex、Claude Code など）の入口です。詳細設計や作業履歴はここに集めず、目的に応じた参照先と、守るべきルールだけを置きます。実装コードとテストが現在の動作の正本で、ドキュメントはコードへ辿るための索引です。

## ドキュメントの参照先

各行は「パス／内容の区分／いつ参照するか、または何に使わないか」の型で書きます。ドキュメントを追加・削除したら、同じコミットでこの一覧も更新してください。文書内のパス参照が存在するかは `python3 scripts/check_doc_paths.py` が CI で検証します。

- `README.md` は公開向けの概要・機能紹介・起動手順・MCP クライアント設定・運用手順です。内部設計の正本としては扱わず、実装との差分が見つかった場合は公開向け説明として修正します。
- `ARCHITECTURE.md` はシステム構成、責務、リクエスト経路、データモデルと不変条件、マイグレーション、CI/CD、変更時のソースマップをまとめた内部設計の正本です。複数レイヤーにまたがる変更では最初に必要な章だけ参照してください。
- `docs/knowledge/README.md` は再利用可能な知見の索引です。作業ログや一時的な状態は追加しません。
- `docs/knowledge/development_conventions.md` はプロジェクト構成、ビルド・テストコマンド、スキーマと契約の同期、実装規約、命名規則、責務分割、テスト方針、サブエージェントの指定、過去の障害から決めた規約をまとめた開発規約です。コードを変更する作業では着手前に必ず読んでください。
- `docs/knowledge/debugging.md` は環境差異（SQLite／PostgreSQL、build／runtime、browser／server）と、認証・検索・移行・画面遷移の切り分け手順です。既知の落とし穴が関係する場合だけ読みます。
- `docs/knowledge/seo-debugging.md` は canonical、index 対象、サイトマップ、Search Console の急変を切り分ける手順です。公開 URL や SEO データに触るときに読みます。
- `docs/knowledge/contracts-and-migrations.md` は REST／MCP の契約と Alembic マイグレーションを変更するときの注意点です。`schemas.py`、`mcp_server.py`、`models.py`、`backend/alembic/versions/` に触るときに読みます。
- `docs/knowledge/parallel_work.md` は git worktree を分けた後の運用手順（共有される DB／ポート、`node_modules`、`.env`、alembic head）です。並列作業を始める前に読みます。
- `docs/knowledge/frontend_visual_verification.md` は Playwright で実描画・実操作を確認する手順です。見た目や操作に影響するフロントエンド変更の PR を作る前に読みます。
- `docs/decisions/README.md` は重要な技術判断（ADR）の索引です。判断を変更・追加するときは、既存 ADR を確認して理由と影響を更新・記録してください。
- `frontend/STYLING_STRATEGY.md` は Next.js 側の CSS 配置（単一の `globals.css` と意味クラス）、カスケード、ブレークポイント、モーションの方針です。UI の変更時は `ARCHITECTURE.md` のフロントエンド章と併せて参照してください。
- `frontend/DESIGN_TOKENS.md` は現在の配色・影・モーションのトークンの参考資料です。新しい UI が既存画面と浮かないよう、色を選ぶ前に読んでください。トークンを変えるときの更新規則は同文書の冒頭にあります。
- `.github/BRANCH_PROTECTION.md` は `main` の保護設定と必須 CI チェックの記録です。マージ条件や CI ゲートを確認・変更するときに参照してください。
- `.env.example` は実行時に読まれる環境変数の一覧と開発値の正本です。環境変数を確認するときはこれを読み、`.env` は読みません。
- `CLAUDE.md` はこのファイルへの誘導だけを置きます。内容はここに書きます。

## 作業開始時の読み方

1. 現在のブランチと未コミットの変更を確認する（`git status`）。
2. 変更対象に近い `ARCHITECTURE.md` の「7. 変更時のソースマップ」を読む。
3. コードを変更するなら `docs/knowledge/development_conventions.md` を読む。
4. 実行方法や環境変数が必要なら `README.md` と `.env.example` を読む。
5. API、データモデル、認証、保存方式、公開 URL を変更する場合は、関連する ADR を読む。

毎回リポジトリ全体や docs 全体を読む必要はありません。

## 重要ファイルの役割

| ファイル／ディレクトリ | 役割 | 詳細な参照先 |
| --- | --- | --- |
| `frontend/` | Next.js の公開画面、SSR、BFF、SEO データ、ブラウザ内保存 | `ARCHITECTURE.md` §2 |
| `frontend/app/globals.css` | 唯一のスタイルシート。トークン、意味クラス、レスポンシブ | `frontend/STYLING_STRATEGY.md` |
| `backend/app/main.py` | FastAPI の認証ミドルウェア、REST/MCP/OAuth の組み立て | `ARCHITECTURE.md` §3 |
| `backend/app/api/` | 内部 REST と OAuth ディスカバリ／認可エンドポイント | `ARCHITECTURE.md` §3.2 |
| `backend/app/mcp_server.py` | MCP ツール、公開／認証要否、共通の例外境界、書き込み入口 | `ARCHITECTURE.md` §3.3、ADR-0020 |
| `backend/app/services/` | 検索、検証、企業同一性、収集キュー、OAuth などのドメイン処理 | `ARCHITECTURE.md` §3.4 |
| `backend/app/models.py` | SQLAlchemy のテーブル、関連、制約 | `ARCHITECTURE.md` §4 |
| `backend/alembic/versions/` | スキーマ変更と既存 DB の移行 | `ARCHITECTURE.md` §6.1、`docs/knowledge/contracts-and-migrations.md` |
| `backend/tests/` / `frontend/**/*.test.*` | ドメイン、認証、移行、UI ロジックの回帰確認 | `docs/knowledge/development_conventions.md` |
| `docker-compose.yml` / `relua.conf` | ローカル構成と公開時のプロキシ境界、healthcheck | `ARCHITECTURE.md` §6.2 |
| `.github/workflows/` | CI（lint・test・build・PostgreSQL 移行）、デプロイ、日次保守 | `ARCHITECTURE.md` §6.3、`.github/BRANCH_PROTECTION.md` |
| `scripts/` | ドキュメントと環境変数の整合を検証する CI 用スクリプト | 各スクリプト冒頭の docstring |
| `docs/knowledge/` | 長期的に再利用できる診断・実装知識 | `docs/knowledge/README.md` |
| `docs/decisions/` | 現在も有効な技術判断と理由 | `docs/decisions/README.md` |

## コミットおよびプルリクエストのガイドライン

- `main` ブランチへ直接 push してはいけません。すべての変更は作業ブランチにコミットし、必ず PR（プルリクエスト）を作成して `main` に取り込んでください。ブランチ名は `fix/<topic>`、`feat/<topic>`、`docs/<topic>`、`perf/<topic>`、`hotfix/<topic>` のように種類を接頭辞にします。
- コミットメッセージは PR タイトルと同じく「日本語の要約 / English summary」の併記で、短くアクション指向にしてください。厳格な conventional-commit 接頭辞は使いません（`fix:`／`feat:` を付けても構いませんが必須ではありません）。
- 1 つの PR に複数の種類の変更（例: バグ修正とリファクタリング、機能追加と無関係な整形など）が含まれる場合は、1 つのコミットにまとめず、変更の種類ごとに複数のコミットに分けてください。
- PR には次を含めます: 背景と変更の明確な説明、関連するイシューや ADR へのリンク（存在する場合）、テストに関するメモ（実行したコマンドと結果）、デプロイ前にサーバー側で必要な作業（`.env` の追加、手動実行が必要な workflow など）があればその明記。UI の変更ではスクリーンショットの添付を推奨しますが、画像はリポジトリにコミットせず PR 本文へ直接添付します。
- PR のタイトルと本文は、日本語と英語の両方を使って作成してください（PR titles and descriptions must include both Japanese and English）。
- エージェントは、ユーザーから明示的な指示がない限り PR をマージしてはいけません。
- `main` へのマージは、直前のマージで起動した CI の実行が完了してから行ってください。`.github/workflows/ci.yml` の concurrency は `cancel-in-progress: true` で `main` にも効くため、連続してマージすると直前のコミットの実行（Deploy ジョブを含む）が打ち切られ、そのコミットがデプロイされないまま「PR は緑」に見える状態が起こりえます。

## エージェントの作業ルール

- 作業開始前に現在のブランチと未コミットの変更を確認してください。
- ユーザーまたは他のエージェントによる既存の変更を、明示的な許可なく上書き、破棄、または巻き戻してはいけません。
- 要件が曖昧なまま実装コードを書かないでください。着手前に質問してスコープとスコープ外を合意し、合意していない変更は加えません。未使用のヘルパー、過剰な抽象化、コメントアウトした残骸などの不要なコードも生成しません。
- コメント、docstring、関数名を仕様の根拠にせず、実装本体とテストを読んで判断してください。触った範囲で実装と食い違うコメントや名前を見つけたら、同じ変更で直します。
- テスト失敗やレビュー指摘に対する自動修正のループは 5 回を上限とします。超えたら自力で続けず、何が未解決でどこで詰まっているかを添えてユーザーに報告してください。
- 実装したエージェントは自分で完了判定をしないでください。コードを変更する PR は、作る前にレビュー用サブエージェント（指定は `docs/knowledge/development_conventions.md` の「サブエージェントの指定」）へスコープ・差分・チェックリスト（要件を満たす／スコープ外の変更が無い／不要なコードが無い／テストが通る／禁止事項に触れない）だけを渡してレビューさせ、実装担当の意図や経緯の説明は渡しません。ドキュメントだけの変更はこのレビューを省略でき、省略した場合は PR 本文にその旨を書きます。指摘は検証してから反映します。指摘に反論がある場合は握りつぶさずユーザーに上げてください。
- 修正後は、変更箇所および直接影響を受ける範囲に対応するテストのみを実行してください。変更と関係のないテストやテストスイート全体は実行しません。ただし、変更が横断的で影響範囲を限定できない場合、またはユーザーが明示的に求めた場合はこの限りではありません。テストを実行できない場合は、その理由を最終報告に記載してください。
- 見た目や操作に影響するフロントエンド変更（CSS、JSX の構造、イベント処理）は、PR を作る前に Playwright で実描画・実操作を確認し、取得したスクリーンショットを実際に目視して、レイアウト崩れ、文字切れ、重なり、余白の破綻がないことを確認してください。確認した画面・ビューポート（PC 幅とスマホ幅）・実測結果を PR 本文に書いてください。手順は `docs/knowledge/frontend_visual_verification.md` にあります。型定義や API クライアントなど描画に出ない変更は対象外です。
- MCP ツールの定義（名前、引数スキーマ、説明文、認証要否）は外部 AI クライアント（ChatGPT、Claude）の挙動を左右する契約です。変更するときは `backend/tests/test_mcp_tools.py` を実行し、`README.md` の「MCPツール」表を同じ変更で同期してください。このリポジトリ自身は LLM を呼び出さないため、プロンプト品質の比較手順はありません。
- サブエージェントと git worktree は別の判断軸です。「作業を独立分割できるか」でサブエージェントを、「作業ツリーを共有すると壊れるか」で worktree を判断してください。
- サブエージェントを使う: 読み取りのみの調査・レビュー、または担当ファイルを重複なく分割できる編集。調査・実装・レビューを分けるときは役割ごとに別の担当にし、各担当にはその役割に必要な情報だけを渡し、原則として同じファイルを同時に編集させないでください。複数の担当に分けるときは、着手前に「誰の成果物を誰にどの形式で渡すか」「何が揃ったら次を始めてよいか」「最終判定は誰か」を決めて各担当の依頼文に書きます。最終判定はユーザーで、エージェント間の判断の不一致はユーザーに上げます。
- worktree を使う（いずれか該当時）: 並列作業が同じ生成物（`backend/alembic/versions/` の head、`frontend/package-lock.json`、`backend/requirements.txt`、`README.md` の MCP ツール表など）に触る／別 PR に分けるべき変更を同時に進める／破棄する可能性のある大規模リファクタ／作業ツリーにユーザーの未コミット変更がある。
- worktree を使わない: 数ファイル規模の変更と、`docker compose up` での起動確認が必要な作業。`.env` は git 管理外で、Compose も backend の設定もリポジトリ直下の `.env` を読むため、新規 worktree ではそのまま起動できません。
- 並行数の上限は worktree の本数ではなく「担当ファイルが重複しないこと」で決めてください。同時に走る作業どうしが同じファイルを編集する予定なら、worktree を増やしても解決しないので片方を待たせます。worktree を分ける単位は着手前に決め、実装途中で思いつきで分割しないでください。並列作業中は担当 worktree の外を触らず、他の作業への依存が判明したら止めてユーザーに報告します。1 worktree = 1 ブランチ = 1 PR とし、共有される DB／ポート、`node_modules`、依存のある作業の順序などの運用手順は `docs/knowledge/parallel_work.md` に従います。
- データベーススキーマを変更する場合は、新しい Alembic migration と関連テストを追加してください。適用済みまたは既存の migration ファイルを書き換えてはいけません（例外と手順は `docs/knowledge/contracts-and-migrations.md`）。
- 新しい依存関係を追加する前に、その必要性と既存の依存関係で代替できないことを確認してください。追加した場合は、理由と影響を PR に記載してください。
- ユーザーへの説明や、作業・編集途中の経過報告はすべて日本語で表示してください。

## ドキュメントを変更するときのルール

- API や DB の仕様を変えるときは、実装・テスト・`ARCHITECTURE.md` のソースマップを同じ変更で確認する。
- 新しい知識は、複数回使えるデバッグ方法・環境差異・失敗回避策だけを `docs/knowledge/` に追加する。単発の作業ログ、実行時ログ、期限のあるメモは保存しない。
- 技術判断を変更したときは、既存 ADR を上書きして履歴を消さず、新しい ADR を追加し、古い ADR を `Superseded` にする。部分的な補正は旧 ADR に `Amended by` を追記する。
- 重要ファイルや参照先を追加・移動したときは、このファイルの表と一覧を更新する。
- `README.md` は利用・運用手順、`ARCHITECTURE.md` は構造、`docs/knowledge/` は方法、`docs/decisions/` は理由を担当させ、同じ説明を複数箇所に複製しない。

## 最低限の検証

変更内容に応じて、次のうち変更範囲に対応するものを使います。全体の方針は `docs/knowledge/development_conventions.md` の「テスト方針」を参照してください。

```bash
cd backend && DATABASE_URL=sqlite:// pytest && ruff check .
cd ../frontend && npm test && npm run lint && npm run typecheck && NEXT_PUBLIC_SITE_URL=http://localhost:3100 npm run build
python3 scripts/check_doc_paths.py && python3 scripts/check_env_documentation.py
```

`npm run build` は `NEXT_PUBLIC_SITE_URL` を要求します。`next build` がこの値を静的ページの canonical・OGP・JSON-LD へ焼き込むため、未設定のビルドを通すと localhost を指したままのページが出来上がるからです（ADR-0019）。

PostgreSQL の Alembic と `pg_trgm` の確認は CI の PostgreSQL ジョブを正本とします。環境差異が疑われる場合は `docs/knowledge/debugging.md` を参照してください。

## セキュリティと設定のヒント

- 必要な環境変数には、内部 API トークン（`API_INTERNAL_TOKEN`）、MCP 用トークン（`MCP_API_TOKEN`）、OAuth 利用時の運営者パスワード（`MCP_OPERATOR_PASSWORD`）、公開 origin（`NEXT_PUBLIC_SITE_URL`）、`ENVIRONMENT`、PostgreSQL の設定、Redis の設定が含まれます。シークレット情報は環境変数または `.env` に保持し、git には含めないでください。
- `local-development-` で始まる値はこのリポジトリに公開されている既知の値です。`ENVIRONMENT=development` を明示したときだけ使え、それ以外では起動が拒否されます（ADR-0019）。
- 実行時に読まれる環境変数の一覧は `.env.example` が正本です。`python3 scripts/check_env_documentation.py` が、コード（`backend/app/config.py`、frontend の `process.env`、`docker-compose.yml`）の読み取りと `.env.example` の記載の同期を検証します。環境変数を追加・削除したら同じ変更で `.env.example` も更新し、必須にする場合は `docker-compose.yml` の `${VAR:?}` と `README.md` の「本番公開前の設定」も更新してください。
- `.env` には秘密情報が入るため、その内容を読んだり、ログ・文書・報告へ転記したりしてはいけません。環境変数の一覧を確認するときは `.env.example` を読んでください。
