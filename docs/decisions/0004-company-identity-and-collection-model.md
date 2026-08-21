# ADR-0004: 企業同一性と収集対象を企業単位で管理する

- Status: Accepted
- Scope: 企業名、別名、業界分類、情報収集キュー

## Context

企業は略称・英語名・旧社名など複数表記を持ち、1社が複数業界に属することもある。業界ごとに収集対象を分けると、同じ企業を二重巡回・二重計上し、別業界の募集が未収集と誤認される。単純な文字列類似だけで企業を統合すると誤結合が起きる。

## Decision

- `companies` の正規化正式名と、公式情報で確認した `company_aliases` の完全一致だけを企業同一性の自動判定に使う。
- fuzzy/trigram 検索は候補提示に限定し、確認後の alias 登録を明示操作にする。
- 企業の業界・業種は `company_industries` に複数保持し、表示用の primary を最大1件だけ持つ。
- `collection_targets` は1企業につき1件とし、公式ページを `collection_sources`、確認履歴を `collection_checks` に分ける。
- 募集の分類は募集自身にも保存し、書き込み時に企業分類へ反映する。

## Consequences

企業件数と巡回件数が一致し、複数業界の企業を二重に扱わずに済む。反面、業界追加は分類の全置換として扱い、企業名の曖昧さは運営者が確認する必要がある。旧スキーマからの統合は [`20260820_0012_add_company_industries.py`](../../backend/alembic/versions/20260820_0012_add_company_industries.py) が担う。

## Code anchors

- `backend/app/models.py` の `Company` / `CompanyAlias` / `CompanyIndustry` / `CollectionTarget`
- `backend/app/services/companies.py`
- `backend/app/services/company_industries.py`
- `backend/app/services/collection_targets.py`
- `backend/tests/test_companies.py`
- `backend/tests/test_collection_targets.py`
