# フロントエンドの実描画確認

[`../../AGENTS.md`](../../AGENTS.md) の作業ルールが求める、見た目や操作に影響する変更の実描画確認の手順です。

## 1. 起動

`next dev` は HMR の websocket が張れないとリンクが full reload に落ちるため、遷移やモーションの観察には向きません。描画だけの確認なら `next dev` でも構いませんが、遷移・スクロール・Data Cache に触る変更は本番ビルドで確認します。

```bash
# 実データで確認する場合（.env のあるリポジトリ直下で）
docker compose up --build
docker compose exec api python -m app.scripts.seed_demo   # 架空データ

# フロントだけ本番ビルドで確認する場合
cd frontend
NEXT_PUBLIC_SITE_URL=http://localhost:3100 npm run build
# next.config.ts は output: "standalone" のため `next start` は警告を出す。本番と同じ入口で起動する
API_INTERNAL_URL=http://127.0.0.1:8000 API_INTERNAL_TOKEN=<開発用トークン> PORT=3100 node .next/standalone/server.js
```

standalone の配置（`.next/static` と `public` のコピー）は [`seo-debugging.md`](./seo-debugging.md) §4 を参照してください。

内部トークンは `.env.example` の開発値を使い、`.env` の内容は読みません。

## 2. 確認するビューポート

| 区分 | 幅 | 理由 |
| --- | --- | --- |
| スマホ | 390px（必須）、360px（狭幅の文字切れ確認） | `globals.css` の 640px 以下ブロックが効く。過去の欠陥（フッターが固定バーの裏、チップの切り取り、見出しの途中切れ）はこの幅で見つかった |
| タブレット | 768px 前後 | 920px 以下で `.shell` が縮み、ディレクトリが 2 列になる。640px 超で PC 用のフィルタ列が残る |
| PC | 1180px 以上（1440px 推奨） | 一覧の 2 カラム、フィルタ列の独立スクロール、コンテンツ幅の上限（約 1160px）を確認する |

テーマ切替は無いため、テーマ間の差異確認はありません。`prefers-reduced-motion: reduce` を有効にした状態で、登場アニメーションの要素が `opacity: 0` のまま残らないことだけ追加で確認します。

## 3. 手順

1. 変更した画面を各幅で開き、フルページのスクリーンショットを取る。
2. 画像を実際に開いて目視する。確認する観点は、レイアウト崩れ、文字切れ（途中改行・省略）、要素の重なり（固定バー・sticky 見出しの裏）、余白の破綻、横スクロールの有無。
3. 操作を伴う変更は、その操作（クリック、フォーム送信、ダイアログの開閉、ページ送り）を実行してから再度スクリーンショットを取る。
4. 横スクロールが無いことは `document.documentElement.scrollWidth <= window.innerWidth` で実測する。スクローラー内の要素のはみ出しは、各要素の `getBoundingClientRect().bottom` を content box の下端と比べる（[`debugging.md`](./debugging.md) §9）。
5. 遷移に触る変更は、`window.__probe = 1` を置いてから遷移し、残っていれば client 遷移、消えていれば full reload と判定する（同 §8）。

Playwright は MCP ツールまたは `npx playwright` のどちらでも構いません。スクリーンショットの保存先はリポジトリ外か `.playwright-mcp/`（git 管理外）にし、リポジトリにはコミットしません。

## 4. PR 本文に書くこと

- 確認した画面（URL）と操作。
- 確認したビューポート幅。
- 実測結果（横スクロールなし、はみ出し要素なし、404／308 の維持など）。
- スクリーンショットを添付する場合は PR 本文へ直接アップロードする。

書き方の例は過去の PR（企業ディレクトリの追加、モバイルレイアウト修正）を参照してください。
