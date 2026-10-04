# Decisions

ここには、現在の構成に影響する技術判断を ADR として残します。実装の細部や作業ログは書かず、背景、採用した案、トレードオフ、コード上の参照先を記録します。

## ADR一覧

| ADR | 判断 | 状態 |
| --- | --- | --- |
| [`0001-private-api-and-next-bff.md`](./0001-private-api-and-next-bff.md) | Next.jsを公開BFF、FastAPIを内部APIとして分離する | Accepted |
| [`0002-mcp-write-safety.md`](./0002-mcp-write-safety.md) | MCP書き込みを検証・冪等化・監査・楽観ロックで保護する | Accepted |
| [`0003-local-browser-data-and-public-codes.md`](./0003-local-browser-data-and-public-codes.md) | ブックマークをブラウザに保持し、短い公開コードで共有する | Accepted |
| [`0004-company-identity-and-collection-model.md`](./0004-company-identity-and-collection-model.md) | 企業同一性と収集対象を企業単位で管理する | Accepted |
| [`0005-confirmed-company-merge.md`](./0005-confirmed-company-merge.md) | 確認済みの重複企業を明示的な物理統合で解消する | Accepted |
| [`0006-existing-company-collection-targets.md`](./0006-existing-company-collection-targets.md) | 既存CompanyをIDで収集対象へ追加し、未監視企業を検出する | Accepted |
| [`0007-expired-opportunity-retention.md`](./0007-expired-opportunity-retention.md) | 締切募集を30日後に完全削除する | Superseded |
| [`0008-manual-expiry-review-queue.md`](./0008-manual-expiry-review-queue.md) | 日付と募集状況の矛盾を要確認キューへ入れ、終了を自動判定しない | Superseded |
| [`0009-soft-date-status-validation.md`](./0009-soft-date-status-validation.md) | 日付と募集状況の矛盾を警告し、書き込みは運営者判断で継続する | Accepted |
| [`0010-write-verification-separation.md`](./0010-write-verification-separation.md) | 募集の更新（write）と一次情報確認（verify）を別の操作にする | Accepted |
| [`0011-tiered-duplicate-identity.md`](./0011-tiered-duplicate-identity.md) | 募集の重複判定を対象学年・実施日・対象職種まで見てexact／probableの2段階にする | Accepted |
| [`0012-mcp-maintenance-eligibility.md`](./0012-mcp-maintenance-eligibility.md) | MCPの定期保守対象を募集予定・募集中・通年募集に限定する | Accepted |
| [`0013-official-source-allowlist-and-check-evidence.md`](./0013-official-source-allowlist-and-check-evidence.md) | 企業公式sourceをallowlistと確認URLの一致で保護する | Accepted |
| [`0014-scheduled-expiry-cleanup.md`](./0014-scheduled-expiry-cleanup.md) | 論理削除の完全削除を監視可能な日次workflowで実行する | Accepted |
| [`0015-canonical-public-urls-and-indexable-facets.md`](./0015-canonical-public-urls-and-indexable-facets.md) | 公開URLを正規化し、単一意図のカテゴリだけをindex対象にする | Superseded |
| [`0016-seo-outage-resilience-and-reviewed-facets.md`](./0016-seo-outage-resilience-and-reviewed-facets.md) | SEOデータを正常スナップショットで保護し、レビュー済みカテゴリallowlistを安定運用する | Accepted |
| [`0017-company-profile-and-public-company-page.md`](./0017-company-profile-and-public-company-page.md) | 企業の事業内容をMCPだけで記録し、公開コードの企業ページで見せる | Accepted |
| [`0018-seo-snapshot-blocking-refresh.md`](./0018-seo-snapshot-blocking-refresh.md) | 期限切れSEOスナップショットを例外ではなくブロッキング再取得で置き換える | Accepted |
| [`0019-fail-closed-secrets-and-trusted-proxy.md`](./0019-fail-closed-secrets-and-trusted-proxy.md) | 公開済みの開発用シークレットと未設定の公開オリジンで起動を止める | Accepted |
| [`0020-mcp-error-boundary-and-master-generation.md`](./0020-mcp-error-boundary-and-master-generation.md) | MCPツールの失敗を一箇所で処理し、マスタキャッシュをスキーマ世代で回す | Accepted |
| [`0021-discovered-sources-stay-inactive.md`](./0021-discovered-sources-stay-inactive.md) | 確認記録で見つかった収集元は無効状態で登録する | Accepted |
| [`0022-sitemap-index-split.md`](./0022-sitemap-index-split.md) | サイトマップを上限超過でインデックス分割する | Accepted |
| [`0023-company-pages-indexed-on-profile-alone.md`](./0023-company-pages-indexed-on-profile-alone.md) | 企業ページのindex条件をプロフィールだけにし、企業ディレクトリを置く | Accepted |
| [`0024-mcp-maintenance-filters-and-company-profile-history.md`](./0024-mcp-maintenance-filters-and-company-profile-history.md) | MCPに保守確認フィルターと企業プロフィール履歴を追加する | Accepted |
| [`0025-batch-company-profile-updates.md`](./0025-batch-company-profile-updates.md) | 企業プロフィールを個別の更新日時照合・保存結果付きで最大50社一括更新する | Accepted |
| [`0026-mcp-maintenance-execution-reporting.md`](./0026-mcp-maintenance-execution-reporting.md) | MCPの確認単位・期限超過除外・実行単位の監査照合を明確にする | Accepted |

新しい判断で既存ADRを置き換える場合は、新しい番号を追加して旧ADRを `Superseded` に更新します。判断が変わっていない限り、日付だけの追記はしません。
