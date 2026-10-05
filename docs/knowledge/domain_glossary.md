# ドメイン用語と状態

relua の利用者、利用の流れ、用語、状態を、画面・REST・MCP・DB・コードで同じ意味に保つための対応表です。定義の正本は実装（[`../../backend/app/models.py`](../../backend/app/models.py)、[`../../backend/app/schemas.py`](../../backend/app/schemas.py)、[`../../backend/app/services/errors.py`](../../backend/app/services/errors.py) の `FIELD_LABELS`）で、この文書はそれらを横断して引く索引です。構造は [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)、判断の理由は [`../decisions/README.md`](../decisions/README.md) にあります。

## 1. 利用者と外部との境界

| 利用者・外部 | 目的 | relua との入出力 | 書き込み |
| --- | --- | --- | --- |
| 閲覧者（就職活動をする学生） | インターン・本選考などの募集を、ログインせずに探して公式ページへたどり着く | 公開画面（Next.js） | しない。保存はブラウザ内だけ（ADR-0003） |
| 運営者 | 企業の公式ページを確認し、募集を正確かつ新しく保つ | 外部 AI クライアント経由の MCP | 唯一の書き込み者 |
| 外部 AI クライアント（ChatGPT、Claude） | 運営者の指示で MCP ツールを呼ぶ | `/mcp`。認証は既定で Bearer トークン（`MCP_API_TOKEN`）、`MCP_OAUTH_ENABLED=true` のときは OAuth。ツールの名前・引数・説明文・認証要否が契約 | 運営者として認証された場合だけ |
| 検索エンジン | 公開ページを index する | canonical URL、index 条件、サイトマップが契約 | しない |
| 企業の公式ページ | 募集の一次情報 | relua のサーバーは取得しない。運営者が読み、確認した URL を記録する | — |

relua にはアカウント・会員・ログインがありません。relua の利用者を指す語として「ユーザー」を使うと閲覧者と運営者のどちらか曖昧になるため、新しく書く文書・コード・UI では「閲覧者」「運営者」と書きます（作業の依頼者を指す「ユーザー」はこの対象外です）。

## 2. 利用の流れ

左から右へ時系列に並べ、各段階を実現する画面・ツールを示します。

### 閲覧者

| 段階 | 探す | 詳細を見る | 保存する | 共有・引き継ぐ | 応募する |
| --- | --- | --- | --- | --- | --- |
| 画面 | `/`、`/companies` | `/opportunities/[id]`（ICS でカレンダーへ追加）、`/companies/[code]` | `/saved`（ブックマーク、JSON・CSV バックアップ） | `/saved` で共有リンク・引き継ぎリンク・QR を作り、`/list`（共有された募集）と `/import`（引き継ぎ）で受け取る | 企業の公式ページ（relua の外） |

### 運営者

| 段階 | 確認する企業を選ぶ | 過去のプロフィールを確認する | 公式ページを確認する | 確認を記録する | 募集を登録・更新する | 矛盾・重複を直す |
| --- | --- | --- | --- | --- | --- |
| MCP ツール | `get_collection_queue`、`list_unmonitored_companies`、`list_undercovered_companies`、`list_companies_missing_profile` | `list_company_profile_history` | `get_company_maintenance_context`、`get_collection_target` | `record_collection_check`、`verify_opportunity` | `resolve_company`、`upsert_opportunity`、`patch_opportunity`、`update_recruitment_status` | `list_stale_opportunities`、`find_similar_opportunities`、`find_opportunities_by_source_url`、`merge_company`、`delete_opportunity` |

ツールの一覧と認証要否の正本は [`../../README.md`](../../README.md) の「MCPツール」表です。

## 3. 用語

1 つの概念を 1 つの名前で呼びます。「日本語名」は `FIELD_LABELS` の表記を正本とし、画面の見出しもこれに寄せます。

| 概念 | 日本語名 | API・MCP | DB | コード |
| --- | --- | --- | --- | --- |
| 募集（インターン、本選考、説明会など 1 件の機会） | 募集、募集情報 | `opportunity`、`*_opportunity` | `opportunities` | `Opportunity`、`services/opportunities.py` |
| 企業 | 企業 | `company`、`company_id` | `companies` | `Company`、`services/companies.py` |
| プロフィール欠落企業 | プロフィール未登録・空欄 | `list_companies_missing_profile`、`missing_profile_fields` | `companies.business_summary`、`companies.description` | `services/companies.py` のプロフィール欠落条件 |
| 企業プロフィール変更履歴 | プロフィール変更履歴 | `list_company_profile_history` | `audit_logs` の `company_profile_update` | `AuditLog`、`services/companies.py` |
| 企業プロフィールの一括更新 | プロフィール一括更新 | `update_company_profiles` | 各社の `company_request_records` と `audit_logs` | `CompanyProfileBatchItemRequest`、`services/companies.py` |
| 書き込み履歴（成功・拒否・結果未確認） | 書き込み履歴 | `list_recent_writes`、`entity_type`（`opportunity`／`company`／`collection_target`／`collection_source`／`collection_check`） | `audit_logs` | `AuditLog`、`services/write_history.py` の `recent_write_logs` |
| 90日より前の運用履歴の保管 | 履歴アーカイブ | MCP一覧の `retention_days` はDB保持日数を通知する。アーカイブ自体は運用専用 | 専用永続ボリュームのJSONL gzip | `services/history_archive.py`、ADR-0028 |
| 実行単位の識別子 | 実行ID | 書き込みツールのトップレベル `run_id`、`list_recent_writes.run_id` | `audit_logs.run_id`（任意、過去の記録はNULL） | `RunId`、`app/audit_context.py`、`AuditLog` |
| 企業別名（略称・英語名・旧社名） | 別名 | `alias` | `company_aliases` | `CompanyAlias` |
| 公開コード（URL・共有に使う 8 文字） | 公開コード | `public_code` | `public_code` 列 | `models.py` の `public_code_string`、公開 URL は `services/serialization.py` |
| 業界／業種 | 業界／業種 | `industry`／`sector` | `industries`／`sectors` | `Industry`／`Sector` |
| 企業の業界分類（多対多） | 業界・業種カテゴリ | `set_company_industries` | `company_industries` | `CompanyIndustry` |
| 募集状況 | 募集状況 | `recruitment_status` | `recruitment_statuses` | `RecruitmentStatus` |
| 募集の登録・編集日時 | 登録日時・最終編集日時 | `created_at`、`updated_at`、`search_opportunity` の `*_at_after`／`*_at_before` | `opportunities.created_at`、`opportunities.updated_at` | `Opportunity`、`services/opportunities.py` |
| 種別（インターン、本選考など） | 種別（画面では「募集種別」） | `event_type` | `event_types` | `EventType` |
| 開催形式 | 開催形式 | `event_format` | `event_formats` | `EventFormat` |
| 対象卒業年 | 対象卒業年 | `graduation_years` | `graduation_years` | `GraduationYear` |
| 収集対象（1 社 1 件の巡回単位） | 情報収集対象 | `collection_target` | `collection_targets` | `CollectionTarget`、`services/collection_targets.py` |
| 企業の公式ページ（採用・インターン・イベント・ニュース） | 公式情報源 | `sources`、`collection_source`、`source_type` | `collection_sources` | `CollectionSource` |
| 確認記録（個別募集の一次情報確認、企業ページの募集なし・確認不能・要確認） | 確認結果 | `record_collection_check`、`result` | `collection_checks` | `CollectionCheck` |
| 募集自身の一次情報 URL | 情報源（一次情報 URL） | `source_url` | `source_url`、`normalized_source_url` | `services/normalization.py` |
| 一次情報を確認した事実 | 公式情報確認日時 | `verify_opportunity`、`source_checked_at` | `source_checked_at` | ADR-0010 |
| 日付と募集中の矛盾を再確認した事実 | 日付矛盾の再確認日時 | `verify_opportunity`、個別募集の `record_collection_check` | `opportunities.date_status_reviewed_at`（内部項目） | ADR-0027 |
| 企業ページを続けて確定できなかった回数 | 連続確認不能回数 | `unreachable`・`needs_review` の確認記録 | `collection_targets.consecutive_failed_checks`（内部項目） | `services/maintenance.py` |
| 収集対象の確認状況（直近の確認結果から導出） | 確認状況 | `check_status` | —（`last_checked_at`、`last_check_result` から導出） | `services/collection_targets.py` の `_check_status` |
| ブラウザ内の保存 | ブックマーク、保存した募集 | —（サーバーに無い） | — | `frontend/lib/local-data.ts` |

既知の揺れ（契約や画面の文言に残っているもの）:

- 「情報源」が、募集の `source_url` と企業の `collection_sources` の両方に使われています。新しく書く文章では前者を「一次情報 URL」、後者を「公式情報源」と書き分け、「収集元」は使いません。
- 対象卒業年が、画面では「卒業年度」、MCP の説明文では「対象学年」とも書かれています。種別は画面で「募集種別」です。
- `source_checked_at` は画面では「公式情報確認」、MCP の説明文では「公式情報確認日時」と「最終確認日時」が混在しています。一方 `FIELD_LABELS` の「更新前の最終確認日時」は `expected_updated_at`（`updated_at` 側）です。新しく書く文章では `source_checked_at` を「公式情報確認日時」と書き、「最終確認日時」だけでは書きません。
- 確認結果（`result`）の `no_opening`／`unreachable` は、収集対象の確認状況（`check_status`）では `no_active_opportunity`／`source_unavailable` と読み替えて返されます。
- これらを一括で改名しません。MCP の説明文や `FIELD_LABELS` は外部 AI クライアントの挙動を左右する契約なので、改名するときは契約変更として扱い（[`contracts-and-migrations.md`](./contracts-and-migrations.md)）、触った箇所から正本の名前に寄せます。

## 4. 同一性を持つものと値

| 区分 | 対象 | 同一性・等価性の決め方 |
| --- | --- | --- |
| 同一性を持つ | 募集 | 内部 UUID。公開には `public_code`。内容が同じでも別の募集はありうる（重複は exact／probable で判定、ADR-0011） |
| 同一性を持つ | 企業 | 内部の整数 ID。同じ企業かどうかは正規化した正式名か明示登録した別名の完全一致だけで決める（ADR-0004） |
| 同一性を持つ | 収集対象 | 1 企業につき 1 件 |
| 値 | 正規化した企業名・タグ・一次情報 URL | `services/normalization.py` の関数で作った結果が等しければ同じ |
| 値 | 日付・当日判定 | `backend/app/dates.py` の東京時間 |
| 値 | 固定値マスタ（業界、業種、募集状況、種別など） | 有効な値だけを名前か slug で解決する。業種は業界でスコープする |

値の検証・正規化は 1 か所の関数に集め、呼び出し側（API、MCP、migration、frontend）で同じ規則を書き直しません。値ごとにクラスを作ることはせず、既存の関数と Pydantic モデル（`schemas.py`）で表します。

## 5. 状態

状態を持つものと、どこまでをシステムが強制するかを示します。不変条件の詳細は [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) §4 にあります。状態を変えるときの規約は [`development_conventions.md`](./development_conventions.md) の「ドメインの境界と業務ルールの置き場所」にあります。

| 対象 | 状態 | 遷移の扱い |
| --- | --- | --- |
| 募集状況 | `募集予定`、`募集中`、`通年募集`、`締切`、`不明` | 遷移の制約は持たず、どの状態へも変更できる。日付との矛盾は拒否せず `warnings` と要確認キューで知らせ、運営者が一次情報で確定する（ADR-0009）。定期再確認の対象は `募集予定`・`募集中`・`通年募集` だけ（`RECONFIRMABLE_RECRUITMENT_STATUSES`、ADR-0012） |
| 募集の公開 | 公開中 → 論理削除（`deleted_at`）→ 復元（同じ UUID・公開コード）または 30 日後に完全削除 | 論理削除は明示操作だけ（ADR-0002）、完全削除は日次ジョブ（ADR-0014）。再送防止記録が残る募集は、その90日保持とアーカイブ完了まで完全削除を保留する（ADR-0028）。締切を過ぎた募集は公開一覧と類似募集から外れ、詳細ページは `noindex` になるが、募集状況も論理削除も自動では変えない（ADR-0012） |
| 収集対象・公式情報源 | 有効／無効（`is_active`） | 削除せず無効化で保持する。確認記録で見つかった公式情報源は無効で登録し、有効化は明示操作（ADR-0021） |
| 確認記録 | `found`、`no_opening`、`unreachable`、`needs_review` | 内容は追記のみ（企業統合での収集対象の付け替えと、完全削除での募集参照の解除を除く）。90日後に原文を圧縮アーカイブへ移す。`found` だけが募集の公式情報確認日時を進める（ADR-0010、ADR-0013、ADR-0028） |
| 収集対象の確認状況 | `unreviewed`、`found`、`no_active_opportunity`、`source_unavailable`、`needs_review` | 保存しない導出値。未確認なら `unreviewed`、それ以外は直近の確認結果から決まる |
| 再確認スケジュール | 確認期限前／確認期限到来 | 確認済みの募集の日付矛盾は `days` 経過まで待機する。企業の `unreachable`・`needs_review` が続く場合は確認間隔を延長し、`found`・`no_opening` で通常間隔へ戻す。無効化や募集状況の変更は自動では行わない（ADR-0027） |
| OAuth の接続 | 有効 → 失効／期限切れ | refresh token の再利用で grant 全体を失効させる（ARCHITECTURE.md §4.4） |
| 運用履歴・再送防止記録の保管 | DB保持 → 作成から90日後に圧縮アーカイブ | アーカイブ保存の検証後にDB行を削除する。アーカイブは無期限保存、同じ要求の再送保証は90日。履歴一覧・件数はDB内の記録を対象とする（ADR-0028） |
