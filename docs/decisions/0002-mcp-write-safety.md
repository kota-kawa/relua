# ADR-0002: MCP書き込みを多層の整合性保護で守る

- Status: Accepted
- Scope: MCPの募集・企業・収集キュー書き込み

## Context

MCPクライアントは通信再試行、部分的な事実、同時接続、古い取得結果を持ち込む可能性がある。公開データを直接更新するため、入力ミスだけでなく、再送による二重登録と stale data による上書きを防ぐ必要がある。

## Decision

- Pydantic schema、固定値解決、日付・URL・自由記述の検証を保存前に必ず通す。
- 企業名・イベント名の重複を検出し、一次情報URLの衝突は確認用 warning として返す。
- すべての書き込みに `request_id` と payload hash を持たせ、同一内容の再送は冪等に処理し、別内容での再利用は拒否する。
- 成功・失敗と before/after を `audit_logs` に保存する。
- 既存の募集情報に対する全項目更新・部分更新・削除は、いずれも `expected_updated_at` による楽観ロックを必須にする。1件のみだけ楽観ロックを外すと、そこだけ stale data による上書き（lost update）を防げなくなるため、既存行への書き込み経路全体を対象にする。
- 削除は論理削除とし、復元時に公開中の重複を再検証する。
- 収集対象への募集登録と `found` 確認は可能な場合同一トランザクションで記録する。

## Consequences

再試行や同時書き込みに強くなり、監査可能性と復元性を得る。一方、クライアントは `request_id`、最新取得、preview→write の順序を守る必要があり、監査ログの保存量も増える。ルールの正本は `backend/app/services/opportunities.py`、`companies.py`、`collection_targets.py` である。

## Code anchors

- `backend/app/mcp_server.py`
- `backend/app/schemas.py`
- `backend/app/services/opportunities.py`
- `backend/app/services/companies.py`
- `backend/app/services/collection_targets.py`
- `backend/app/models.py` の `AuditLog` / `IdempotencyRecord` / request record
