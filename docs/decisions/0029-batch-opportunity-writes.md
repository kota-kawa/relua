# ADR-0029: 募集の登録と一次情報確認を個別結果付きで一括処理する

- Status: Accepted
- Scope: MCPの募集一括登録・確認、取得引数の互換性、事前検証の応答
- Related: [ADR-0025](./0025-batch-company-profile-updates.md)、[ADR-0026](./0026-mcp-maintenance-execution-reporting.md)、[ADR-0010](./0010-write-verification-separation.md)

## Context

企業プロフィールには一括更新があるが、募集の追加と確認記録は1件ずつの呼び出しが必要だった。外部AIクライアントの実行中に調査と保存を進める際、この呼び出し数が処理件数を制約する。また、詳細取得だけ引数が `reference` で、書き込み時の `opportunity_id` を渡すと引数エラーになる。事前検証の「保存できます」という応答は、入力検証への合格と実際の保存成功の区別を曖昧にしていた。

## Decision

- `upsert_opportunities` と `verify_opportunities` を認証付きで追加する。各ツールは `items` に1〜50件、共通の `run_id` をトップレベルに受け取る。各件の `request_id` は別にする。
- 募集登録は単件の `upsert_opportunity`、一次情報確認は単件の `verify_opportunity` を再利用し、URL・固定値・重複・日時の検証、冪等化、監査、行ロックを維持する。内容更新と確認を別の操作とするADR-0010は維持する。
- 個別入力は外側の件数・オブジェクト型の検証後に各件で検証する。入力不備・対象不明・内部エラーで他の項目を止めず、個別トランザクションで成功分を保持する。内部エラーは共通例外境界で本文を隠し、監査にも結果未確認として記録する。
- 応答は入力順の個別結果と集計で、本文の全文を再送しない。処理成功数には既存返却・再試行も含むため、今回の新規登録・確認数を別に返す。完全な重複で返した既存募集の内容・確認日時は変更しない。
- 保存後の応答エラーでも結果未確認とする。同じ内容・同じ `request_id` で再送して照合できる。既存返却や処理済み再試行では新しい成功監査記録を作らず、実績は監査件数と同一ではない。
- `get_opportunity` は既存の `reference` を維持し、`opportunity_id` も受け付ける。少なくとも一方を要求し、両方が指定され値が異なる場合は拒否する。
- 事前検証の合格応答は「Reluaの入力検証に合格」「未保存」を明示する。クライアント側の安全チェックや認証、実際の保存時の競合の通過を保証しない。

## Consequences

募集の登録・確認の呼び出し数を減らしながら、企業プロフィールと同様に部分失敗から復帰できる。既存の単件契約は維持し、DB変更や新しい依存関係は不要である。公式ページ調査と外部クライアントの実行上限・安全チェックは引き続きクライアント側にある。一括化は安全チェックの回避手段ではない。接続側は追加されたツール定義を取得し直す必要がある。

## Code anchors

- `backend/app/mcp_server.py` の `get_opportunity`、`_run_opportunity_batch`、`upsert_opportunities_tool`、`verify_opportunities_tool`
- `backend/app/schemas.py` の `OpportunityBatchUpsertRequest`、`OpportunityBatchVerifyRequest`、`MCPOpportunityBatchWriteResponse`
- `backend/tests/test_mcp_tools.py`
