# ADR-0006: 既存CompanyをIDで収集対象へ追加し、未監視企業をCompany起点で検出する

- Status: Accepted
- Scope: 収集対象の追加、企業マスタの棚卸し、MCP書き込み

## Context

募集登録や過去の取り込みにより、Companyは存在するが `collection_targets` を持たない企業がある。名前だけで収集対象を追加すると、未登録の略称・誤記で新しいCompanyを作るおそれがあり、既存Companyの採用ページを確実に監視対象へ結び付けられない。また、収集対象を起点とした一覧だけでは、未作成の企業を検出できない。

## Decision

- `add_collection_target` は既存Companyの `company_id` または新規企業の `company_name` のどちらか一方を必須とする。
- `list_unmonitored_companies` はCompanyを起点に、収集対象がない企業を募集件数・企業分類とともに返す。
- 運営者は既存Companyを監視対象へ追加するとき、一覧または `resolve_company` が返すIDを使う。名前の完全一致・別名解決による従来の新規追加も維持する。

## Consequences

Companyマスタにだけ存在する企業を一括で修復でき、名称の再入力による重複作成を避けられる。`company_id` は運用者向けの内部IDなので、ツールは認証を要する。一覧結果は監視漏れの棚卸し用であり、企業を自動的に収集対象へ昇格させない。

## Code anchors

- `backend/app/schemas.py` の `CollectionTargetCreateRequest`
- `backend/app/services/collection_targets.py` の `list_unmonitored_companies`
- `backend/app/mcp_server.py` の `list_unmonitored_companies` / `add_collection_target`
- `backend/tests/test_collection_targets.py`
- `backend/tests/test_mcp_tools.py`
