# ADR-0014: 論理削除の完全削除を監視可能な日次workflowで実行する

- Status: Accepted
- Amended by: [ADR-0028](./0028-history-archive-and-idempotency-retention.md)（履歴アーカイブとOAuth掃除を追加）
- Scope: 論理削除済み募集の保持期限、運用scheduler、失敗監視

## Context

完全削除コマンドだけをREADMEに記載しても、サーバー側cronが実際に設定されたか、停止していないかをリポジトリから確認できない。論理削除後30日の保持方針と実運用がずれると、不要データが残り続けても検知しにくい。

## Decision

- default branchのGitHub Actions scheduleから毎日02:15 JSTに `app.scripts.close_expired` をSSH実行する。
- 同じworkflowを `workflow_dispatch` でも実行できるようにし、導入時と障害復旧時に手動検証できるようにする。
- コマンドの終了コードに加え、`purged=<件数>` の完了markerを検証する。SSH、Compose、DB、コマンドのいずれかが失敗した場合はworkflowを失敗させる。
- 運用者はActionsの失敗通知を有効にし、workflow履歴を実行監視の正本とする。

## Consequences

scheduler設定と実行結果がリポジトリ／Actionsに残り、停止を失敗として検知できる。一方でGitHub Actions、SSH、デプロイ用Secretsへ依存するため、リポジトリをfork・移管した場合はSecretsと通知設定を再構成する必要がある。

## Code anchors

- `.github/workflows/maintenance.yml`
- `backend/app/scripts/close_expired.py`
- `backend/tests/test_expiry_cleanup.py`
- `docs/usage.md` の「運用」
