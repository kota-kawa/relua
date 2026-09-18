# AGENTS.md

## このファイルの使い方

このリポジトリで作業する Codex の入口です。ここには詳細設計や作業履歴を集めず、目的に応じた参照先だけを置きます。

- 起動・MCP接続・運用コマンドを確認する: [`README.md`](./README.md)
- システム全体、責務境界、データモデル、リクエスト経路を確認する: [`ARCHITECTURE.md`](./ARCHITECTURE.md)
- 再現性のあるデバッグ手順や環境差異を確認する: [`docs/knowledge/README.md`](./docs/knowledge/README.md)
- 重要な技術判断と採用理由を確認する: [`docs/decisions/README.md`](./docs/decisions/README.md)

## 作業開始時の読み方

1. 変更対象に近い `ARCHITECTURE.md` の「ソースマップ」を読む。
2. 実行方法や環境変数が必要なら `README.md` と [`.env.example`](./.env.example) を読む。
3. 既知の落とし穴が関係する場合だけ [`docs/knowledge/debugging.md`](./docs/knowledge/debugging.md) を読む。
4. API、データモデル、認証、保存方式を変更する場合は、関連する ADR を読む。

毎回リポジトリ全体や docs 全体を読む必要はありません。実装コードとテストが現在の動作の正本で、ドキュメントはコードへ辿るための索引です。

## 重要ファイルの役割

| ファイル／ディレクトリ | 役割 | 詳細な参照先 |
| --- | --- | --- |
| `README.md` | 利用者・運用者向けの起動、MCP、運用、検証手順 | [`ARCHITECTURE.md`](./ARCHITECTURE.md) の運用境界 |
| `ARCHITECTURE.md` | フロントエンド、バックエンド、DB、認証、デプロイの構造 | 実装ファイルへのリンク付き |
| `frontend/` | Next.js の公開画面、SSR、BFF、ブラウザ内保存 | `ARCHITECTURE.md` §2 |
| `backend/app/main.py` | FastAPI の認証ミドルウェア、REST/MCP/OAuth の組み立て | `ARCHITECTURE.md` §3 |
| `backend/app/api/` | 内部RESTとOAuthディスカバリ／認可エンドポイント | `ARCHITECTURE.md` §3.2 |
| `backend/app/mcp_server.py` | MCPツール、公開／認証要否、書き込み入口 | `ARCHITECTURE.md` §3.3 |
| `backend/app/services/` | 検索、検証、企業同一性、収集キュー、OAuthなどのドメイン処理 | `ARCHITECTURE.md` §3.4 |
| `backend/app/models.py` | SQLAlchemy のテーブル、関連、制約 | `ARCHITECTURE.md` §4 |
| `backend/alembic/versions/` | スキーマ変更と既存DBの移行 | `ARCHITECTURE.md` §5 |
| `docker-compose.yml` / `relua.conf` | ローカル構成と公開時のプロキシ境界 | `ARCHITECTURE.md` §6 |
| `backend/tests/` / `frontend/**/*.test.*` | ドメイン、認証、移行、UIロジックの回帰確認 | [`docs/knowledge/debugging.md`](./docs/knowledge/debugging.md) |
| `docs/knowledge/` | 長期的に再利用できる診断・実装知識 | [`docs/knowledge/README.md`](./docs/knowledge/README.md) |
| `docs/decisions/` | 現在も有効な技術判断と理由 | [`docs/decisions/README.md`](./docs/decisions/README.md) |

### 今回追加した資料

| ファイル | 役割 |
| --- | --- |
| [`docs/knowledge/README.md`](./docs/knowledge/README.md) | knowledge文書の追加基準と索引 |
| [`docs/knowledge/debugging.md`](./docs/knowledge/debugging.md) | Python/DB/Next.js/MCPの環境差異、認証・検索・移行の切り分け |
| [`docs/knowledge/seo-debugging.md`](./docs/knowledge/seo-debugging.md) | canonical、index対象、Search Console急変の切り分け |
| [`docs/decisions/README.md`](./docs/decisions/README.md) | ADRの一覧と更新ルール |
| [`docs/decisions/0001-private-api-and-next-bff.md`](./docs/decisions/0001-private-api-and-next-bff.md) | Next.js BFFとFastAPI内部APIの採用理由 |
| [`docs/decisions/0002-mcp-write-safety.md`](./docs/decisions/0002-mcp-write-safety.md) | MCP書き込みの検証・冪等化・監査・ロックの理由 |
| [`docs/decisions/0003-local-browser-data-and-public-codes.md`](./docs/decisions/0003-local-browser-data-and-public-codes.md) | localStorage保存と公開コード共有の理由 |
| [`docs/decisions/0004-company-identity-and-collection-model.md`](./docs/decisions/0004-company-identity-and-collection-model.md) | 企業同一性、複数業界、企業単位収集の理由 |
| [`docs/decisions/0012-mcp-maintenance-eligibility.md`](./docs/decisions/0012-mcp-maintenance-eligibility.md) | MCPの定期保守対象を現行募集の状態に限定する理由 |
| [`docs/decisions/0013-official-source-allowlist-and-check-evidence.md`](./docs/decisions/0013-official-source-allowlist-and-check-evidence.md) | 企業公式source allowlistと確認証跡の理由 |
| [`docs/decisions/0014-scheduled-expiry-cleanup.md`](./docs/decisions/0014-scheduled-expiry-cleanup.md) | 完全削除を日次schedule化し監視する理由 |
| [`docs/decisions/0015-canonical-public-urls-and-indexable-facets.md`](./docs/decisions/0015-canonical-public-urls-and-indexable-facets.md) | 公開URL正規化とindex対象カテゴリの理由 |
| [`docs/decisions/0016-seo-outage-resilience-and-reviewed-facets.md`](./docs/decisions/0016-seo-outage-resilience-and-reviewed-facets.md) | SEOデータの障害耐性、レビュー済みカテゴリallowlist、サイトマップ503の理由 |
| [`docs/decisions/0017-company-profile-and-public-company-page.md`](./docs/decisions/0017-company-profile-and-public-company-page.md) | 企業プロフィールをMCP限定で書く理由と、企業ページのURL・index条件 |
| [`docs/decisions/0018-seo-snapshot-blocking-refresh.md`](./docs/decisions/0018-seo-snapshot-blocking-refresh.md) | 期限切れSEOスナップショットを待って再取得する理由と、読み取りAPI再試行の条件 |

## 変更時のルール

- APIやDBの仕様を変えるときは、実装・テスト・`ARCHITECTURE.md` のソースマップを同じ変更で確認する。
- 新しい知識は、複数回使えるデバッグ方法・環境差異・失敗回避策だけを `docs/knowledge/` に追加する。単発の作業ログ、実行時ログ、期限のあるメモは保存しない。
- 技術判断を変更したときは、既存ADRを上書きして履歴を消さず、新しいADRを追加し、古いADRを `Superseded` にする。
- 重要ファイルや参照先を追加・移動したときは、このファイルの表を更新する。
- `README.md` は利用・運用手順、`ARCHITECTURE.md` は構造、`docs/knowledge/` は方法、`docs/decisions/` は理由を担当させ、同じ説明を複数箇所に複製しない。

## 最低限の検証

変更内容に応じて、README の検証コマンドまたは次を使います。

```bash
cd backend && DATABASE_URL=sqlite:// pytest && ruff check .
cd ../frontend && npm test && npm run lint && npm run build
```

PostgreSQL の Alembic と `pg_trgm` の確認は CI の PostgreSQL ジョブを正本とします。環境差異が疑われる場合は [`docs/knowledge/debugging.md`](./docs/knowledge/debugging.md) を参照してください。
