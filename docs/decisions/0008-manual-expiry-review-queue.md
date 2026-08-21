# ADR-0008: 日付と募集状況の矛盾は手動確認キューで扱う

- Status: Accepted
- Scope: 募集の終了判定、日次確認、削除ライフサイクル
- Supersedes: [ADR-0007](./0007-expired-opportunity-retention.md)

## Context

締切日または実施終了日が過去でも、締切延長や追加募集により公式ページ上では「募集中」のままであることがある。日付だけを根拠に状態を「締切」へ変更し論理削除すると、公開すべき募集を誤って隠すおそれがある。

## Decision

- `list_stale_opportunities` は、東京基準で `deadline < today` または `event_end_date < today` かつ募集状況が「募集中」の募集を、通常の公式情報未確認より優先して返す。
- 応答には、期限超過・実施終了日のどちらが矛盾しているかを `review_reasons` として含める。
- この検出は保存済みフラグではなく毎回のクエリで行い、正しい日付や状況へ更新すれば直ちにキューから外れる。
- Reluaは矛盾を検出しても、募集状況の変更・論理削除を自動では実行しない。運営者は公式情報を確認し、`verify_opportunity` または更新ツールで確定する。
- 日次ジョブは手動・明示的な論理削除から30日経過した募集だけを完全削除する。

## Consequences

募集の公開可否は公式情報を確認した運営者が判断する。確認作業は増えるが、期限延長・追加募集を誤って非公開にするリスクを避けられる。動的キューのため、日次バッチでフラグを作成・解消するための追加テーブルや移行は不要である。

## Code anchors

- `backend/app/services/opportunities.py` の `list_opportunities_requiring_review`
- `backend/app/mcp_server.py` の `list_stale_opportunities`
- `backend/app/scripts/close_expired.py`
- `backend/tests/test_mcp_tools.py`
- `backend/tests/test_expiry_cleanup.py`
