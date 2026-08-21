# ADR-0009: 日付と募集状況の矛盾はsoft validationで通知する

- Status: Accepted
- Scope: 募集情報の追加・更新・事前検証

## Context

募集を「締切」にした直後に「募集中」へ戻すような操作は、最終状態が正しくても途中の人為的な誤操作を示す。未来の締め切りや実施開始日と「締切」、過去の締め切りや実施終了日と「募集中」は機械的に検出できる。

ただし、締切延長、追加募集、イベント中止などにより、日付だけでは正しい状態を自動判定できない。

## Decision

- 追加、全項目更新、部分更新、募集状況更新、事前検証・部分更新プレビューで、日付と募集状況の矛盾を `warnings` として返す。
- `締切` と未来の締め切り／実施開始日、`募集中` と過去の締め切り／実施終了日を対象にする。
- warning は保存を拒否せず、公式情報を確認して運営者が更新内容を確定する。

## Consequences

既存の例外的な募集を登録できる柔軟性を保ちつつ、通常の更新で見過ごしやすい不整合をMCPクライアントへ明示できる。warning を無視して保存することもできるため、監査と日次の要確認キューを併用する。

## Code anchors

- `backend/app/services/opportunities.py` の `opportunity_consistency_warnings`
- `backend/app/mcp_server.py`
- `backend/tests/test_mcp_tools.py`
