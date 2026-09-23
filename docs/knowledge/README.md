# Knowledge

ここには、複数の作業で再利用できる開発規約・診断方法・環境差異・失敗回避策だけを置きます。単発の調査メモ、作業ログ、実行時ログ、期限のある情報は置きません。

## 使い分け

- システムの構造やコードの場所を探す: [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)
- 起動・運用コマンドを確認する: [`../../README.md`](../../README.md)
- なぜその構成になっているかを確認する: [`../decisions/README.md`](../decisions/README.md)
- コードを変更する前に規約を確認する: [`development_conventions.md`](./development_conventions.md)（構成、コマンド、同期すべきもの、命名、責務分割、テスト方針、サブエージェントの指定、過去の障害から決めた規約）
- 利用者・利用の流れ・用語・同一性・状態を確認する: [`domain_glossary.md`](./domain_glossary.md)
- 再現・切り分け方法を確認する: [`debugging.md`](./debugging.md)
- 検索流入、canonical、index対象の回帰を確認する: [`seo-debugging.md`](./seo-debugging.md)
- REST／MCP の契約や Alembic migration を変える: [`contracts-and-migrations.md`](./contracts-and-migrations.md)
- git worktree を分けて並列に作業する: [`parallel_work.md`](./parallel_work.md)
- 見た目に触る変更を Playwright で確認する: [`frontend_visual_verification.md`](./frontend_visual_verification.md)

## 文書追加の基準

次のいずれかを満たす場合だけ、テーマごとに追加します。

- 失敗しやすく、同じ確認を今後も行う。
- SQLite／PostgreSQL、build／runtime、browser／server など、環境の違いで結果が変わる。
- 複数の実装箇所やテストにまたがるため、コードコメントだけでは辿りにくい。

新しい知見は既存の章に追記できるかを先に確認し、日付順のログにはしません。過去の不具合から一般化した規約は `development_conventions.md` の「過去の障害・手戻りから決めた規約」に、由来の PR 番号と一緒に 1 行で追記します。文書を追加・削除したら [`../../AGENTS.md`](../../AGENTS.md) の「ドキュメントの参照先」も同じコミットで更新します。
