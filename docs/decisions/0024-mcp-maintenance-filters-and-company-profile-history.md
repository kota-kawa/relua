# ADR-0024: MCPに保守確認フィルターと企業プロフィール履歴を追加する

- Status: Accepted
- Scope: 運営者向けMCP読み取りツール、募集検索、収集対象の確認状況、企業プロフィール監査履歴
- Related: [ADR-0017](./0017-company-profile-and-public-company-page.md)

## Context

企業プロフィールの公開条件は一言説明（`business_summary`）と事業内容本文（`description`）の両方が登録済みであることだが、その欠落企業をMCPから一覧する手段がなかった。募集の登録日時・最終編集日時は検索結果に一部しか表示されず、呼び出し側が指定する期間で絞り込めなかった。収集対象には直近の確認状況があるものの、状態別に棚卸しできなかった。企業プロフィール更新は監査ログに前後の値と出典URLを保存しているが、MCPから企業単位で読み返せなかった。

## Decision

- `list_companies_missing_profile` は `business_summary` または `description` がNULL・空欄の企業を返し、収集対象の有無には依存させない。欠けている項目名を各行に含め、企業名・業界による絞り込みとページングを提供する。
- `search_opportunity` は `created_at` と `updated_at` の下限・上限を受け付ける。すべての境界を含み、カーソルの検索条件シグネチャにも日時条件を含める。匿名入力を日時解析前に64文字以内へ制限し、検索一覧では `created_at` と `updated_at` の両方を返す。
- `list_collection_targets` は導出済みの `check_status` を複数選択でOR絞り込みする。確認状態は既存の `last_checked_at` と `last_check_result` から導出し、保存列やmigrationは追加しない。
- `list_company_profile_history` は企業IDに対応する成功済み `company_profile_update` 監査ログを新しい順で返す。既存ログに含まれる変更前後のプロフィールと公式ページURLを使い、別の履歴テーブルは作らない。
- これらの読み取りツールは運営者認証を要求する。公開中の募集検索は既存どおり匿名利用できる。

## Consequences

運営者はプロフィールの欠落、募集の古い登録・編集、確認結果別の収集対象をMCPだけで抽出できる。プロフィールを書き換える前に、過去の値と参照元を企業単位で確認できる。いずれも既存データを読み取るため、DBスキーマ変更とmigrationは不要である。

日時範囲は呼び出し側が指定する必要がある。日時を省略した入力はUTCとして扱う。プロフィール履歴は成功した更新操作の監査記録に依存し、監査ログが存在しない過去の更新を再構成することはしない。

## Code anchors

- `backend/app/mcp_server.py` の `search_opportunity`、`list_collection_targets`、`list_companies_missing_profile`、`list_company_profile_history`
- `backend/app/services/opportunities.py` の `search_opportunities`
- `backend/app/services/collection_targets.py` の `list_collection_targets`
- `backend/app/services/companies.py` のプロフィール欠落検索・プロフィール履歴読み取り
- `backend/app/schemas.py`、`backend/app/services/serialization.py`
- `backend/tests/test_mcp_tools.py`, `test_opportunities.py`, `test_collection_targets.py`, `test_companies.py`
