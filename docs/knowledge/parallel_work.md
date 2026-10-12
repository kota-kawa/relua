# worktree を分けた後の運用手順

worktree を分ける判断基準は [`../../AGENTS.md`](../../AGENTS.md) の「エージェントの作業ルール」にあります。ここでは分けた後に何が共有され、何を分けるかだけを書きます。

## 1. 共有されるもの

| 対象 | 状態 | 扱い |
| --- | --- | --- |
| `.env` | git 管理外。リポジトリ直下にしか無い | 新規 worktree には存在しないため `docker compose up` も backend の `Settings`（`env_file="../.env"`）も動かない。起動が必要な作業は元の作業ツリーで行う。コピーする場合も内容は読まない |
| Docker Compose のプロジェクト | ディレクトリ名から決まる | worktree ごとに別プロジェクトになり、`postgres_data`／`redis_data` volume も別になる。既定のポート（`API_LOOPBACK_PORT`=8000、`FRONTEND_PORT`=3100）はホストで共有されるため、同じ `.env` で 2 つは起動できない。起動は 1 か所に限る |
| PostgreSQL のデータ | volume 単位 | Compose を 1 か所で起動する前提なら共有されない。DB を直接触る確認は起動している側で行う |
| `frontend/node_modules` | git 管理外 | worktree ごとに `npm ci` が必要。`package-lock.json` を変える作業が 2 つ同時に走ると衝突するため、依存追加は 1 本に限る |
| `backend/.venv` | git 管理外 | 別 worktree からも絶対パスで使える（`/path/to/main/backend/.venv/bin/pytest`）。依存を変える作業だけ別に作る |
| Alembic の head | git 管理 | 2 本の作業が migration を追加すると head が 2 本になる。schema 変更を伴う作業は同時に 1 本まで。後から取り込む側が `down_revision` を付け替える |
| `docs/usage.md` の MCP ツール表・`ARCHITECTURE.md` のソースマップ・`AGENTS.md` の一覧 | git 管理 | 複数の作業が同じ表を編集すると衝突する。表の更新は各作業の最後にまとめ、取り込み順を決めておく |
| Next.js のビルドキャッシュ（`frontend/.next/`） | git 管理外 | worktree ごとに独立。本番ビルドでの Data Cache 確認は `.next/cache/fetch-cache` が worktree ごとに別になる |

## 2. 分ける単位と順序

- 1 worktree = 1 ブランチ = 1 PR です。1 つの worktree で複数 PR を切り替えません。分ける判断と並行数の上限は `AGENTS.md` の規則に従います。
- 依存のある作業（例: schema 変更 → それを使う API → それを表示する UI）は、上流の PR がマージされてから下流を rebase して進めます。上流が未マージのうちに下流を作るときは、下流ブランチを上流ブランチから切り、PR の base を上流にします。

## 3. 作成と片付け

```bash
git worktree add ../relua-<topic> -b <type>/<topic> main
cd ../relua-<topic>/frontend && npm ci          # frontend を触る場合
# 作業・PR 作成後
cd /path/to/relua && git worktree remove ../relua-<topic>
```

- テストは worktree 内で回します。`DATABASE_URL=sqlite://` の pytest は他の worktree と干渉しません。
- PostgreSQL 実機の確認が必要な場合は、Compose を起動している作業ツリーの `db` に対して、確認したい worktree のコードで `alembic upgrade head` を実行します。既存データを壊す確認（`drop_all`）は本番相当データの上で行いません。
- 片付けの前に `git status` で未コミットの変更が無いことを確認します。worktree の削除は作業ツリーだけで、ブランチは残ります。
