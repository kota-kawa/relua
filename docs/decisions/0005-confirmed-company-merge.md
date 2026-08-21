# ADR-0005: 確認済み重複企業は明示的な物理統合で解消する

- Status: Accepted
- Scope: Companyの重複解消、募集・収集データの移管、MCP書き込み

## Context

別名の登録は新規の募集・収集対象を同じCompanyへ解決するが、すでに作られた重複Companyそのものと、その募集・収集履歴は残る。Companyを単純に削除すると、募集、収集対象、確認履歴、企業別名、企業操作の冪等性記録への参照を失う。一方、名前の類似だけで統合すると別法人を誤結合する危険がある。

## Decision

- `merge_company(source_company_id, target_company_id)` は、運営者が公式情報で同一の採用主体と確認した後に、明示したIDを使って実行する。
- 1トランザクション内で募集、旧正式名を含む別名、企業分類、収集対象・情報源・確認履歴、企業書き込みの冪等性記録を統合先へ移す。
- 統合先にも収集対象がある場合は1件へ畳み、同一URLの情報源だけを重複排除する。確認履歴はすべて残す。
- 旧正式名は統合先の別名として残し、旧表記による解決を維持する。第三者の正式名・別名との衝突は失敗として扱い、勝手に移さない。
- 統合元Companyは移管後に物理削除する。`audit_logs` は不変の履歴として保持し、操作は `request_id` で冪等にする。

## Consequences

企業マスタを実際に1レコードへ収束でき、旧名による検索と既存の公開募集リンクを保てる。物理削除は一般の募集削除より復元コストが高いため、ツールはOAuth認証と破壊的操作の注記を持ち、IDの指定と公式情報による事前確認を必須の運用とする。統合後に同名の募集が複数残る可能性はあるが、内容を失わないため自動削除はしない。

## Code anchors

- `backend/app/mcp_server.py` の `merge_company`
- `backend/app/services/companies.py` の `merge_company`
- `backend/app/schemas.py` の `MCPCompanyMergeResponse`
- `backend/tests/test_companies.py`
- `backend/tests/test_mcp_tools.py`
