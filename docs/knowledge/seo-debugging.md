# SEOの回帰を切り分ける

検索流入が急変したときに、インデックス対象の変更、canonicalの分散、順位変動を混同しないための確認順です。単日の総クリック率だけで原因を決めず、同じURL群・クエリ群・掲載順位で比較します。

## 1. URL群を分ける

Search Consoleのドメインプロパティで、変更前後の同じ曜日範囲を比較します。

- canonical詳細: `/opportunities/[A-Z0-9]{8}`
- 旧UUID詳細: `/opportunities/[0-9a-f-]{36}`
- 一覧パラメータ: `/?`
- apexと`www`

一覧パラメータだけ表示回数が減り、詳細の平均掲載順位が変わらなければ、`noindex`対象の整理が主因です。詳細全体の平均掲載順位が同時に下がれば、コンテンツ品質やランキング更新を別に調べます。apexの減少と`www`の増加が対応する場合は、URLプレフィックス単位の計測移動です。

## 2. 公開レスポンスの不変条件

デプロイ後は実サイトで次を確認します。

```bash
curl -I https://www.relua.net/example
curl -I https://relua.net/opportunities/<UUID>
curl -sS https://relua.net/opportunities/<PUBLIC_CODE> | rg 'canonical|robots|application/ld\+json'
curl -I https://relua.net/companies/<小文字の公開コード>
curl -sS https://relua.net/companies/<PUBLIC_CODE> | rg 'canonical|robots'
curl -sS https://relua.net/sitemap.xml | rg -o '<loc>[^<]+'
```

- `www`は同じpath/queryを保ってapexへ308になる。
- UUID詳細は対応する公開コード詳細へ308になる。
- 公開コード詳細は自己参照canonicalを持つ。
- 内部リンクとサイトマップにUUIDや`www`が含まれない。
- 終了済み募集は`noindex, follow`、応募可能な募集は`index, follow`になる。
- 自由検索・複合絞り込み・範囲外ページは`noindex, follow`になる。
- 企業ページは自己参照canonicalを持ち、小文字の公開コードは大文字URLへ308になる。存在しない公開コードは404になる。
- 一言説明（`business_summary`）と本文（`description`）のどちらかが未登録、または現在の募集が0件の企業ページは`noindex, follow`になる。3つすべてを満たす企業だけ`index, follow`になる。

リダイレクトはレスポンス本文のmeta refreshではなくHTTP statusを確認します。App Routerがplaceholderを先にストリーミングすると、ページコンポーネント内のredirectが200応答になるため、旧URLの解決は`frontend/proxy.ts`で描画前に行います。範囲外ページと存在しない詳細は`loading.tsx`を置かず、HTTP 404を確定させます。

## 3. サイトマップとビルド時API

frontend imageのbuild時は、同じComposeで起動するAPIがまだ到達不能な場合があります。サイトマップを静的生成すると、その時のfallbackがデプロイ後も残り得ます。`/sitemap.xml`は`app/sitemap.xml/route.ts`の実行時生成を維持し、次を確認します。

- `<loc>`件数が現在の募集予定・募集中・通年募集の詳細＋静的ページ＋固定allowlist内で正常1件以上のカテゴリになる。
- 詳細URLは公開コードだけになる。
- 企業URLは`/companies/<公開コード>`で、`GET /api/v1/companies?indexable=true`の件数と一致する。`noindex`の企業ページは含まれない。ページのrobotsとサイトマップが食い違う場合は、企業APIの条件（一言説明と本文の有無・現行募集の有無）とページ側の`companyIsIndexable`のどちらが古いかを比べる。
- `lastmod`は内容更新と公式情報確認日時の新しい方になる。
- カテゴリ件数をカテゴリごとのAPI呼び出しで数えず、取得済み全件から集計する。
- 募集API・master API・企業APIのいずれかの取得に失敗したときは、4ページだけの200ではなく503、`Retry-After: 300`、`Cache-Control: no-store`になる。正常な0件のときだけ静的4ページの200になる。

## 4. Search Consoleでの確認

修正後はサイトマップを再送信し、代表URLについてURL検査を行います。

- トップ
- index対象カテゴリ
- noindex対象の複合絞り込み
- canonical公開コード詳細
- 旧UUID詳細

「ユーザーが指定した正規URL」と「Googleが選択した正規URL」が一致することを確認します。URL削除ツールはcanonical統合には使いません。変更を短期間に反転させず、URL群ごとのクロール・index・平均掲載順位を継続して比較します。
