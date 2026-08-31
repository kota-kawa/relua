# Knowledge

ここには、複数の作業で再利用できる診断方法・環境差異・失敗回避策だけを置きます。単発の調査メモ、作業ログ、実行時ログ、期限のある情報は置きません。

## 使い分け

- システムの構造やコードの場所を探す: [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)
- 起動・運用コマンドを確認する: [`../../README.md`](../../README.md)
- なぜその構成になっているかを確認する: [`../decisions/README.md`](../decisions/README.md)
- 再現・切り分け方法を確認する: [`debugging.md`](./debugging.md)
- 検索流入、canonical、index対象の回帰を確認する: [`seo-debugging.md`](./seo-debugging.md)

## 文書追加の基準

次のいずれかを満たす場合だけ、テーマごとに追加します。

- 失敗しやすく、同じ確認を今後も行う。
- SQLite／PostgreSQL、build／runtime、browser／server など、環境の違いで結果が変わる。
- 複数の実装箇所やテストにまたがるため、コードコメントだけでは辿りにくい。

新しい知見は既存の章に追記できるかを先に確認し、日付順のログにはしません。
