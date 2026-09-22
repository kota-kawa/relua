# スタイリング方針

Next.js 側の CSS をどこに置き、どう重ねるかの方針です。画面の責務と遷移の構成は [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §2、色とモーションの値は [`DESIGN_TOKENS.md`](./DESIGN_TOKENS.md) を参照してください。

## 1. 配置

- スタイルシートは `app/globals.css` の 1 ファイルだけです。CSS Modules、styled-jsx、コンポーネントごとの CSS ファイルは使いません。
- 先頭の `@import "tailwindcss"` は base スタイル（リセット）のために読み込んでいます。JSX にユーティリティクラスを並べる書き方はしておらず、`className` には役割を表す意味クラス（`.discovery-bar`、`.filter-summary`、`.card-grid`）だけを置きます。新しい UI も同じ方法で書きます。
- `globals.css` は画面の順（Header → Hero → Discovery navigation → Results and filters → Cards → Detail → Company page／directory → About／Terms → Local bookmarks → Footer → Toast → 入力デバイス → 920px／640px のブレークポイント → reduced motion）に章分けされ、各章は `/* 見出し */` コメントで始まります。新しい部品はその画面の章に足し、末尾に追記しません。
- 「なぜこの指定が必要か」は CSS のコメントに書きます（例: `position: relative` が包含ブロックを閉じるために load-bearing であること）。理由の無い `!important` や魔法の数値を置きません。

## 2. カスケードの順

1. `:root` のトークン（色、影、モーション、`--discovery-bar-h`）。
2. 部品の基本スタイル（意味クラス）。
3. 状態の修飾クラス（`.filter-summary-compact`、`.view-list` など、親に付く状態クラスを含む）。
4. 入力デバイスの分岐: 面の浮き上がりや色の反転など目立つ hover は `@media (hover: hover)` の中に置き、タッチ端末に hover が残らないようにする。下線やアイコンの微小な移動程度のリンク hover は部品の章に直接書かれているものがある。`:active` の押下フィードバックは全端末共通。
5. ブレークポイント: 末尾の `max-width: 920px`（タブレット、`.shell` 幅の縮小、ディレクトリを 2 列に）と `max-width: 640px`（スマホ。ヘッダー縮小、フィルタをボトムシートへ、チップ行の分離、ディレクトリを 1 列に）の 2 ブロックが本体です。企業ディレクトリの章には余白だけを調整する `max-width: 720px` が部品に隣接して置かれています。デスクトップ優先で書き、狭い幅で上書きします。
6. `@media (prefers-reduced-motion: reduce)`: 全体の duration/delay を潰したうえで、`opacity: 0` から始まる登場アニメーションは `animation: none` で明示的に止めます。止め忘れると内容が見えないまま残ります。

新しいセレクタはこの順の中の該当位置に置き、後ろの章で前の章を上書きして辻褄を合わせることはしません。

## 3. レイアウトの前提

- 横幅は `.shell` が管理します（PC は `min(1180px, calc(100% - 48px))`、920px 以下と 640px 以下で縮む）。部品側で `max-width` を持たせず、`.shell` の中に置きます。
- ドキュメントのスクローラーは `scroll-behavior: auto` のままにします。App Router の遷移中に長距離スクロールが走るためで、詳細は [`../docs/knowledge/debugging.md`](../docs/knowledge/debugging.md) §7。
- 独立したスクローラー（フィルタ列など）を増やすときは、絶対配置の子孫を行単位の `position: relative` で閉じます（同 §9）。
- 固定要素（モバイルの CTA バー、フィルタの浮動ボタン、トースト）はページ全体に `transform` を掛ける祖先を持ってはいけません。ページの登場は fade のみで rise しないのはそのためです。
- ダイアログとボトムシートは native `<dialog>` を使います。開いている間は `body:has(dialog[open])` でページのスクロールを止め、閉じるモーションは `display: none` になる前に終わるよう CSS 側で管理します（該当章のコメント参照）。

## 4. モーション

- 使う曲線は `--ease-settle`（到着）と `--ease-standard`（その場での状態変化）の 2 つ、長さは `--dur-quick`／`--dur-base`／`--dur-enter` の 3 つだけです。新しい値を足さず、この中から選びます。
- 一覧の登場は `.results-flow` の子に `rise-in` を掛け、`lib/motion.ts` の `stagger()` が与える `--stagger`（順番）に CSS 側の `--stagger-step` を掛けて遅延を作ります。順番の上限も `motion.ts` 側で決まります。
- 同じ key で再描画される要素は DOM が再利用され、CSS animation は再実行されません。「もう一度登場させたい」ときは key を変えます。

## 5. レガシー互換

- 旧 UUID の詳細 URL、小文字の公開コード、`www`・HTTP からのリダイレクトは `proxy.ts` と `relua.conf` が担当し、CSS には関係しません。
- ブラウザ差の分岐は `@supports (transition-behavior: allow-discrete)`（ボトムシートの閉じモーション）の 1 か所だけです。追加する場合は同じように該当部品に隣接して置き、非対応時の見え方を基本スタイルで成立させます。
- クラス名を変更するときは、Vitest（`components/*.test.tsx`）がクラス名で要素を取っている箇所を同じ変更で直します。
