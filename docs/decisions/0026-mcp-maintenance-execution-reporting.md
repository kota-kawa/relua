# ADR-0026: MCP保守の確認単位と実行単位の保存実績を明確にする

- Status: Accepted
- Scope: 収集確認のMCP契約、要確認募集の絞り込み、実行単位の監査履歴
- Amends: [ADR-0002](./0002-mcp-write-safety.md)、[ADR-0012](./0012-mcp-maintenance-eligibility.md)

## Context

外部AIクライアントが企業の採用トップページを個別募集の確認として記録すると、募集自身の一次情報URLとの照合で拒否される。多数の企業を調査してから保存を始める進め方では、クライアントの実行が途中で止まると確認結果が残らない。期限超過の募集を操作しない指示に対して、状態矛盾を最優先に返すキューを取得後に除外しても、取得上限が矛盾だけで埋まり、通常の再確認へ進めない。

監査履歴をクライアント名だけで読むと、そのクライアントによる複数の実行が混在する。1回の募集登録が付随する確認記録も作るため、履歴件数は更新企業数やツール呼び出し数とも一致しない。

## Decision

- `record_collection_check` の `found` は、登録済み個別募集のIDとその一次情報URLを実際に確認した場合と明記する。新しい募集は先に登録する。企業ページだけの確認は募集IDを指定せず、有効な登録済み公式情報源と `no_opening`・`unreachable`・`needs_review` を使う。確認単位とURL照合の検証自体は維持する。
- URL不一致は期待するURLだけでなく、実際の再確認、企業単位の記録、新規募集の登録、入力修正時の新しい `request_id` を案内する。URLを差し替えただけでは確認済みにできないことを明記する。
- サーバー指示と収集ツールで、少数社ずつ確認・更新・記録を完了する進め方を案内する。外部クライアントの実行上限や未保存の調査結果の持ち越しはReluaで保証しない。
- `list_stale_opportunities` に任意の `exclude_expired` を追加する。trueでは締め切り・実施終了日のいずれかが東京時間の当日より前の募集をSQLの件数制限前に除外する。当日・日付未設定は残す。既定のfalseはADR-0012の矛盾優先を維持する。企業単位の新規募集発見は抑制しない。
- 全書き込みツールに任意のトップレベル `run_id` を追加し、監査ログのnullable列と索引で保持する。共通MCP例外境界でContextVarのスコープを設定し、監査ログ挿入時に付与する。ネストする一括更新と付随する記録も同じ実行IDを持ち、終了・例外・同時呼び出しでスコープが混ざらない。
- 実行IDは相関のための情報で、冪等性のpayload hashへ加えない。処理済み再試行は新しい監査記録を作らず、元の実行IDを変更しない。過去の履歴への推測による実行IDの補完は行わない。
- `list_recent_writes` は実行IDの完全一致・既存のクライアント／対象種類の条件で絞り込み、ページングと全該当監査記録の成功・拒否・結果未確認件数を返す。件数は企業数や呼び出し数ではない。一括更新の内部エラー記録は `code=internal_error` とし、結果未確認を拒否と区別する。
- 監査記録のない未実行・通信失敗・引数検証失敗・内部エラーは、履歴だけでは保存結果を確定できない。保存後の応答エラーでは成功記録と結果未確認記録が共存するため、集計を操作の最終結果と読み替えない。全ページの照合は書き込み終了後に行う。

## Consequences

既存の呼び出しを維持しながら、確認単位の取り違えから復帰する手順と、同じ実行の監査記録を照合する手段を提供できる。DBには新しいmigrationが必要だが、既存行や冪等記録は変更しない。MCPクライアントは追加された引数・説明を取得するため、接続のツール定義を更新する必要がある。

## Code anchors

- `backend/app/mcp_server.py` のツール定義と共通例外境界
- `backend/app/audit_context.py`、`backend/app/models.py` の `AuditLog`
- `backend/app/services/collection_targets.py`、`backend/app/services/opportunities.py`、`backend/app/services/write_history.py`
- `backend/app/schemas.py`
- `backend/alembic/versions/20261004_0016_add_audit_run_id.py`
- `backend/tests/test_mcp_tools.py`、`backend/tests/test_audit_context.py`、`backend/tests/test_audit_run_migration.py`、`backend/tests/test_opportunities.py`
