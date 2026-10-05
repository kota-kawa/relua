# ADR-0027: 再確認が完了した対象を次回期限まで保守キューから外す

- Status: Accepted
- Scope: 募集の要確認キュー、企業の未カバー一覧、確認不能の再確認間隔
- Amends: [ADR-0010](./0010-write-verification-separation.md)、[ADR-0012](./0012-mcp-maintenance-eligibility.md)、[ADR-0026](./0026-mcp-maintenance-execution-reporting.md)

## Context

期限が過去でも公式ページでは募集中の募集を確認すると、確認日時だけが進み、日付矛盾が取得枠に残る。募集の少ない企業の一覧は次回確認日を使わず、確認したばかりの企業も繰り返し返す。確認不能・要確認が続く企業も同じ間隔で確認され、他の対象の確認と履歴保存を圧迫する。

## Decision

- 初めて検出した期限・実施終了日と募集中の矛盾は、従来どおり最優先に返す。自動で募集状況・日付・公開条件を変えない。
- `verify_opportunity` または個別募集の `found` 確認で、確認したJST当日に矛盾があれば `date_status_reviewed_at` を記録する。同じ矛盾は `list_stale_opportunities` の `days`（既定7日）が経過するまで再取得しない。新規登録や企業ページの確認では記録しない。
- 募集状況、締め切り、実施終了日、一次情報URL、企業の変更と復元ではこの記録を解除する。本文・タグだけの編集は維持する。いずれの内容更新も公式情報確認日時を進めない。
- 募集の少ない企業の一覧は、通常収集キューと同じ未確認・次回確認期限の条件をSQLの取得上限前に適用する。同じ募集件数では未確認、次回確認日、企業名の順に返す。
- `unreachable` と `needs_review` の連続確認は、結果が両者の間で変わっても同じ連続回数として数える。初回は設定間隔、以後は2倍・4倍と延長し、90日または元の設定間隔の大きい方を上限とする。連続回数は8で頭打ちにする。
- `found`・`no_opening` と新規募集の同時確認は連続回数を0へ戻し、通常間隔へ戻す。同一要求の再送では回数・次回確認日を変えない。確認不能だけを理由に自動で無効化しない。
- 設定間隔の変更は連続回数を考慮して次回日を再計算する。企業統合では直近の確認結果と連続回数を一緒に引き継ぎ、既存の早い確認期限を維持する。

## Consequences

再確認済みの対象が取得枠を埋め続けることと、解消できない企業の頻繁な再巡回を抑えられる。確認不能が続く企業は再発見が遅れるため、運営者は収集対象を直接確認・更新できる。新しい列は既存募集でNULL、既存企業で連続回数0とし、過去の確認の意味を推測して補完しない。

## Code anchors

- `backend/app/services/maintenance.py`
- `backend/app/services/opportunities.py`
- `backend/app/services/collection_targets.py`
- `backend/app/services/companies.py`
- `backend/alembic/versions/20261005_0017_add_maintenance_review_schedule.py`
- `backend/tests/test_maintenance_schedule_migration.py`
