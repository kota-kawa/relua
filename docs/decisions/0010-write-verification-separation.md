# ADR-0010: 募集の更新と一次情報確認を別の操作にする

- Status: Accepted
- Scope: 募集情報の更新・部分更新、`source_checked_at`、収集対象への確認記録
- Amended by: [ADR-0013](./0013-official-source-allowlist-and-check-evidence.md)（確認URLと `opportunity_id` の必須条件を追加）

## Context

`write_opportunity` は新規登録・全項目更新・部分更新を1つの関数で扱っており、いずれの操作でも `source_checked_at`（一次情報確認日時）を `updated_at` と同時に更新し、`collection_target_id` が指定または自動一致すれば収集対象の `found` 確認まで同時に記録していた。

これは新規登録では正しい。新しい募集を登録する行為は、その場で一次情報を読んだことを意味する。しかし既存募集の更新・部分更新では成立しない。たとえば「タグだけを直す」「表記ゆれを修正する」といった、一次情報を読み直さない保守操作でも同じ経路を通るため、DBの内容を書き換えただけで「今、公式ページを確認した」という意味のfreshnessまで更新されてしまう。長期運用では `source_checked_at` が実態より新しく見え続け、本当に確認が必要な募集が要確認キュー（`list_stale_opportunities`）から漏れる。

## Decision

- `write_opportunity` が `source_checked_at` を更新し、収集対象への `found` 確認を記録するのは新規登録（`opportunity_id` を指定しない呼び出し）のときだけにする。
- 全項目更新・部分更新（`update_opportunity`／`patch_opportunity`）は保存対象のフィールドだけを書き換え、`source_checked_at` に触れない。両ツールから `collection_target_id` 引数を削除し、更新経路へ指定された場合は明示的な検証エラーにする。
- 一次情報を実際に確認した事実は、既存の `verify_opportunity`（内容不変の確認）または `record_collection_check`（収集対象単位の確認、`opportunity_id` 指定可）で別途記録する。この2つはどちらも `updated_at` を変えず `source_checked_at` だけを進める。
- つまり write（DBの内容を変える）と verify（一次情報を確認した事実を記録する）を常に別の呼び出しにする。同じ操作で両方を行いたい場合も、呼び出し側が明示的に2回呼ぶ。

## Consequences

タグ修正のような一次情報を読み直さない保守操作が、確認済みの見た目を偽らなくなる。反面、内容修正と同時に確認も記録したい呼び出し側は、更新後に `verify_opportunity` または `record_collection_check` をもう1回呼ぶ必要がある。収集対象への `found` 記録は新規登録時に限られるため、既存募集の更新経由で収集対象の `last_checked_at`／`next_check_at` を進めたい場合も、`record_collection_check` を明示的に呼ぶ。

## Code anchors

- `backend/app/services/opportunities.py` の `write_opportunity`（`is_new` 分岐）、`verify_opportunity`
- `backend/app/services/collection_targets.py` の `record_collection_check`
- `backend/app/mcp_server.py` の `update_opportunity`／`patch_opportunity_tool`
- `backend/app/models.py` の `Opportunity.source_checked_at`
- `backend/tests/test_opportunities.py`、`backend/tests/test_mcp_tools.py`
