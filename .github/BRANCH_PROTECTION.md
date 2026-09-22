# main ブランチの保護設定

`main` のマージ条件と必須 CI チェックの記録です。設定を変えたら同じ変更でこの文書を更新します。

## 現在の状態

GitHub 上の `main` にはブランチ保護ルールもリポジトリルールセットも設定されていません（`gh api repos/<owner>/<repo>/branches/main/protection` が 404、`rulesets` が空）。直接 push を禁じているのは [`../AGENTS.md`](../AGENTS.md) の運用ルールだけです。

## 目標とする設定

リポジトリの Settings → Branches（または Rules）で次を設定します。

| 項目 | 値 | 理由 |
| --- | --- | --- |
| Require a pull request before merging | 有効 | 直接 push の禁止を運用ではなく設定で守る |
| Required approvals | 0（個人開発のため） | レビューはサブエージェントと本人が担う |
| Require status checks to pass before merging | 有効。必須チェックは下記 | CI が緑でないコミットを `main` に入れない |
| Require branches to be up to date before merging | 有効 | 直前のマージとの組み合わせを CI で確認する |
| Do not allow bypassing the above settings | 有効 | 管理者も同じゲートを通る |
| Allow force pushes / deletions | 無効 | デプロイの起点となる履歴を守る |

### 必須ステータスチェック

[`workflows/ci.yml`](./workflows/ci.yml) のジョブ名です。

- `Backend Lint & Test`（Ruff、SQLite テスト、PostgreSQL の Alembic と `pg_trgm`、関連度検索）
- `Frontend Lint & Build`（ESLint、`tsc --noEmit`、Vitest、`next build`）
- `Docs & Env Consistency`（ドキュメントのパス参照と `.env.example` の同期）

`Deploy (main push)` は `main` への push でだけ動くため必須チェックにしません。

## マージの運用

- マージはユーザーが行います。エージェントは明示的な指示がない限りマージしません。
- 連続してマージしない。`ci.yml` の concurrency は `cancel-in-progress: true` で `main` にも効くため、前のマージの実行（Deploy を含む）が終わる前に次をマージすると前の実行が打ち切られ、そのコミットがデプロイされません。
- Deploy が失敗した場合、ワークフローは直前のコミットへ `git reset --hard` して再起動します。デプロイログの `Deployment Diagnostics` を確認してから次のマージを行います。
- 日次保守（[`workflows/maintenance.yml`](./workflows/maintenance.yml)）はマージとは独立に動きます。失敗通知を有効にしておきます。
