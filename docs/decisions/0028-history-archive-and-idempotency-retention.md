# ADR-0028: 履歴を90日後に圧縮アーカイブへ移し、再送保証を90日にする

- Status: Accepted
- Scope: 監査・確認履歴、再送防止記録、OAuthの不要な記録、日次保守
- Amends: [ADR-0002](./0002-mcp-write-safety.md)、[ADR-0014](./0014-scheduled-expiry-cleanup.md)、[ADR-0026](./0026-mcp-maintenance-execution-reporting.md)

## Context

企業や募集が増えなくても、確認・更新のたびに監査ログ、確認履歴、再送防止記録が追記される。募集の完全削除はこれらの全体を整理しない。日次保守は論理削除済み募集だけを対象としており、履歴は無期限にDBを大きくする。

## Decision

- 運営者との合意により、履歴のDB保持を90日、圧縮アーカイブの保持を無期限、同一要求の再送保証を90日とする。
- `audit_logs`、`collection_checks`、`idempotency_records`、`company_request_records`、`collection_request_records` の `created_at` が90日より前の行を、一定件数ずつJSONL gzipへ移す。90日ちょうどの記録は残す。新しい再送防止記録が参照する確認履歴と企業統合の監査スナップショットは保護する。
- 元の全列をアーカイブに保存する。ファイルを永続化して読戻し検証した後だけ、対象のDB行を削除する。失敗ではDB行を保持し、DB削除が失敗してからの再実行でも記録を失わない。ファイルの内容ハッシュで同じ記録の重複保存を抑える。
- アーカイブはAPIコンテナの専用 `history_archive` 永続ボリュームに置く。公開画面・MCPからファイルを公開せず、運用バックアップに含める。アーカイブは履歴の原文であり、現在の企業・募集の行へは戻さない。
- MCPの履歴一覧と件数集計はDB内の記録だけを扱う。レスポンスの `retention_days` と説明文で範囲を知らせる。90日より前の履歴は運用アーカイブから確認する。
- 募集の完全削除は、紐付く再送防止記録が残る間は保留する。先に履歴をアーカイブし、90日以内の保証と、保管失敗時に未保存の記録が連鎖削除されないことを守る。
- 90日より前の `request_id` の再送は、再実行や対象の不在による拒否になる場合があり、以前の応答の再現は保証しない。内容を修正した操作には従来どおり新しい `request_id` を使う。
- OAuthの期限切れ認可コードの掃除を日次で実行する。期限切れaccess tokenと、接続が終了したgrantの不要なtokenを90日経過後にアーカイブへ移す。有効grantの使用済みrefresh tokenは、再利用検知でgrant全体を失効させるためDBに残す。登録済みclientと現在の接続は消さない。
- 日次workflowは履歴のアーカイブ、募集の完全削除、OAuthの認可コード掃除を順に実行し、各コマンドの終了コードと固有の完了markerを検証する。

## Consequences

頻繁に更新しても、DB内の運用履歴は原則直近90日に限定される。圧縮アーカイブは増え続けるが、監査の根拠は失わず、DBの検索・バックアップから古い原文を分離できる。アーカイブのバックアップと保管容量の監視が必要となる。有効なOAuth接続の再利用検知記録は保持の例外となる。

## Code anchors

- `backend/app/services/history_archive.py`
- `backend/app/scripts/archive_history.py`
- `backend/tests/test_history_archive.py`
- `.github/workflows/maintenance.yml`
- `docker-compose.yml`
