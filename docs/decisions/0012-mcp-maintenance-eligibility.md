# ADR-0012: MCP定期保守の対象状態を現行募集に限定する

- Status: Accepted
- Scope: MCPの募集再確認、企業保守コンテキスト、収集対象の募集一覧
- Supersedes: [ADR-0008](./0008-manual-expiry-review-queue.md)
- Amended by: [ADR-0026](./0026-mcp-maintenance-execution-reporting.md)（任意の期限超過除外）

## Context

締切済みの募集やすでに終了した募集を、公式情報の定期確認キューへ繰り返し返すと、確認作業と不要な更新が発生する。一方、募集状況が「募集中」のまま締切日または実施終了日を過ぎた募集は、締切延長や追加募集の可能性があるため、公式情報を確認して状態を確定する必要がある。

## Decision

- 定期再確認の対象状態を「募集予定」「募集中」「通年募集」のallowlistとする。allowlistにない「締切」「不明」や将来追加される終了状態は、通常の再確認キューから除外する。
- `list_stale_opportunities` と `list_opportunities_requiring_review` は、上記の対象状態だけを返す。
- 「募集中」かつ締切日または実施終了日が東京基準の当日より前の募集は、対象状態から除外せず、通常の未確認より優先して返す。Reluaは自動で「締切」へ変更せず、運営者が公式情報を確認して更新する。
- `get_company_maintenance_context` と収集対象レスポンスの `opportunities` は、定期再確認対象だけを返す。終了状態の募集はIDを指定する直接の参照・更新や重複確認のために保持するが、保守一覧には含めない。
- 企業単位の `get_collection_queue` 自体は、新しい募集を発見するために、現在の対象募集がない企業も返す。終了状態だけが紐付く企業は、募集一覧上は未カバーとして扱う。

## Consequences

MCPクライアントは、定期確認の結果をそのまま更新対象へ渡しても、締切済み・終了済みの募集を通常の保守処理へ持ち込みにくくなる。期限超過中の「募集中」は引き続き見落とさず、手動で「締切」へ確定できる。

終了状態の募集を明示的に訂正・再開する必要がある場合は、`get_opportunity` でIDを取得して更新ツールを直接呼ぶ。新しい募集の発見を目的とする企業単位の収集は、既存募集が終了していても継続する。

## Code anchors

- `backend/app/services/opportunities.py`
- `backend/app/services/collection_targets.py`
- `backend/app/mcp_server.py`
- `backend/tests/test_opportunities.py`
- `backend/tests/test_collection_targets.py`
- `backend/tests/test_mcp_tools.py`
