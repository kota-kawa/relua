# ADR-0016: SEOデータの障害耐性とレビュー済みカテゴリallowlist

- Status: Accepted
- Scope: 一覧・詳細のSSR metadata、カテゴリindex、サイトマップ、旧URL転送
- Supersedes: [ADR-0015](./0015-canonical-public-urls-and-indexable-facets.md)

## Context

一覧のmetadata生成と本文が別々にAPIを呼んでいたため、一時的なAPI障害の瞬間に、同じカテゴリが本文のエラー表示を200で返しながらmetadataだけ`noindex`になる可能性があった。サイトマップも募集APIが失敗したとき静的4ページだけを正常な200として返し、数千件のURLが一時的に消えていた。

カテゴリのindex可否を募集件数の5件・8件などの閾値で決めると、在庫の増減で同じURLがindex／noindexを繰り返す。公開URLをUUIDから公開コードへ集約する方針はすでに有効であり、これを変更せず旧UUIDから最終URLへ直接転送する必要がある。

## Decision

- 一覧・詳細は、metadataと本文で同じ正規化キーの完全成功スナップショットを共有する。Next.js Data Cacheの`unstable_cache`を60秒で再検証し、Reactのリクエスト内`cache`で重複取得を抑える。API fetch自体は`no-store`とし、失敗した再検証結果で最後の正常値を上書きしない。
- スナップショットは最後の正常取得から1時間まで利用できる。冷たいキャッシュの失敗または1時間を超えた値は例外を伝播させ、画面を200＋`noindex`／ErrorStateへ縮退させない。API復旧後は再検証の成功値へ戻る。詳細のAPI 404だけは`null`という正常結果としてキャッシュして404にし、関連企業募集の失敗は空配列として主ページを維持する。
- crawlerへmetadataをブロッキングで返すため`htmlLimitedBots: /.*/`を設定する。主データ取得失敗時はHTTP 5xxとし、送信済み200のmetadataを後から変更する経路を作らない。
- サイトマップは`/sitemap.xml`の実行時routeで、募集全ページとmasterが成功した場合だけ完全なXMLを200で返す。部分失敗は`503`、`Retry-After: 300`、`Cache-Control: no-store`を返す。正常に0件なら静的4ページだけを200で返す。URLは引き続き公開コードだけを使う。
- index可能カテゴリは本番で確認したレビュー済みの型付きallowlistを正本とし、業界14・業種50・職種18・募集種別5・開催形式3・卒業年度5を初期値とする。allowlist内の単一カテゴリは正常結果が1件以上ならindexし、正常0件は404としてサイトマップから除外する。件数の5／8閾値による切り替えは行わない。過去卒年の除外は既存の`currentGraduationYears`を維持し、新しい卒年はallowlistへ手動追加する。
- allowlist外、複合条件、検索、並び替えなどの`noindex`方針、自己canonical、範囲外ページ404は維持する。
- 旧UUID詳細はwww判定より先にmiddlewareで解決し、`https://relua.net/opportunities/{PUBLIC_CODE}`へ1回の308を返す。API 404は404、5xx・通信失敗・不正な公開コードは503とする。通常の公開コードURLにUUID解決API呼び出しは追加しない。www／HTTPの旧UUIDだけをNginxからNextへ渡し、その他のURLは既存のapex HTTPS 308を維持する。

## Consequences

APIが短時間停止しても、直前の正常な画面とmetadataを最大1時間利用でき、Googlebotへ誤った`noindex`や部分サイトマップを返しにくくなる。長時間障害では5xxが継続するため、API復旧と5xx・サイトマップ件数の監視が必要になる。カテゴリURLの集合は在庫件数から独立して安定する一方、新しいカテゴリや卒年は設定変更とレビューが必要である。

## Code anchors

- `frontend/lib/seo-data.ts`
- `frontend/lib/api.ts`
- `frontend/app/page.tsx`
- `frontend/app/opportunities/[id]/page.tsx`
- `frontend/lib/seo.ts`
- `frontend/lib/sitemap.ts`
- `frontend/app/sitemap.xml/route.ts`
- `frontend/proxy.ts`
- `frontend/next.config.ts`
- `relua.conf`
