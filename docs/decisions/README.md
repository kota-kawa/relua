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

新しい判断で既存ADRを置き換える場合は、新しい番号を追加して旧ADRを `Superseded` に更新します。判断が変わっていない限り、日付だけの追記はしません。
