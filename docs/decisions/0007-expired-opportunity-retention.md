# ADR-0007: 締切募集を30日後に完全削除する

- Status: Superseded by [ADR-0008](./0008-manual-expiry-review-queue.md)
- Scope: 募集の削除ライフサイクル、日次運用、データ保持量

## Context

締切済みの募集は公開価値が低く、論理削除だけでは `opportunities` と関連する中間テーブル・冪等性レコードが増え続ける。一方、削除直後は誤判定や復元要求に対応できる余地が必要である。

## Decision

- 日次の `close_expired` ジョブは、東京基準で締切日を過ぎた募集を「締切」に更新し、論理削除する。
- `deleted_at` から30日を経過した募集は同じジョブで物理削除する。手動で論理削除した募集も同じ保持期限の対象とする。
- 物理削除時、収集確認履歴は残して `opportunity_id` をNULLにする。募集の中間テーブルと冪等性レコードは外部キーのcascadeで削除し、監査ログは外部キーを持たない履歴として保持する。
- ジョブはcronまたはデプロイ基盤のスケジューラーで1日1回実行する。

## Consequences

締切済みデータは31日程度でDBから除去され、公開データと書き込み用補助データの増加を抑えられる。論理削除後30日だけは `restore_opportunity` で復元できるが、物理削除後は復元・既存共有リンクの復旧はできない。

## Code anchors

- `backend/app/scripts/close_expired.py`
- `backend/app/models.py` の `Opportunity` / `CollectionCheck` / `IdempotencyRecord`
- `backend/tests/test_expiry_cleanup.py`
