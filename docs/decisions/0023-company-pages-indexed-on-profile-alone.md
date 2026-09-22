# ADR-0023: 企業ページのindex条件をプロフィールだけにし、企業ディレクトリを置く

- Status: Accepted
- Scope: 企業ページのindex条件、企業一覧API、`/companies` ディレクトリ、サイトマップ、企業の`lastmod`
- Amends: [ADR-0017](./0017-company-profile-and-public-company-page.md)

## Context

[ADR-0017](./0017-company-profile-and-public-company-page.md) は、企業ページのindex対象を「`business_summary` と `description` の両方が登録済み」かつ「現在の募集が1件以上ある」企業に限った。狙いは、名前しか持たない企業マスタの数百社が空のページとして検索対象に増えるのを防ぐことだった。

しかし2つの条件のうち、その狙いを達成しているのは前者だけである。プロフィールには入力検証で最小文字数（一言説明30字、本文300字、各事業60字）が課されており、登録済みという事実そのものが「読むに足る分量がある」ことを保証している。募集件数はこの保証に何も足していない。

一方で、後者の条件には [ADR-0016](./0016-seo-outage-resilience-and-reviewed-facets.md) がカテゴリページから意図的に取り除いた性質がある。

> カテゴリのindex可否を募集件数の5件・8件などの閾値で決めると、在庫の増減で同じURLがindex／noindexを繰り返す。

閾値が5から1になっても性質は変わらない。企業の募集は締切を過ぎれば現在の募集でなくなるため、同じ企業ページが募集期ごとにindexと`noindex`を往復する。

さらに ADR-0017 は「企業名リンクは募集詳細ページ（heroの企業名と「同じ企業の他の募集」）にだけ置く」と定めている。企業ページへの内部リンクは、その企業の募集詳細ページにしか存在しない。募集がすべて終了しても詳細ページ自体は残るため孤立はしないが、終了済み詳細は `noindex, follow` であり、企業ページはindexされたページからのリンクを失う。index判定と内部リンクの評価が同時に弱まる設計になっていた。

## Decision

- 企業ページのindex条件から現在の募集を外し、プロフィールの登録だけを条件とする。`GET /api/v1/companies?indexable=true` が正本である点と、サイトマップを同じ一覧から作る点は ADR-0017 のまま維持する。
- 一覧クエリの募集集計は内部結合から外部結合に変える。集計は件数を供給するだけで、絞り込みには使わない。
- `openings_updated_at` は現在の募集だけでなく、終了済みを含む全募集の最新 `updated_at` とする。現在の募集だけから計算すると、最後の募集が締切を過ぎた日に `lastmod` がプロフィール更新日まで巻き戻る。過去の募集を含めれば単調に進み、巻き戻らない。企業ページ詳細の `dateModified` も同じ基準で揃える。
- `/companies` に企業ディレクトリを置く。プロフィールを持つ全企業を名前順で並べ、企業名リンクと一言説明を載せる。1ページ100件、`?page=N` でページングし、範囲外と不正な `page` は404とする。未知のクエリキーは無視する（流入リンクのキャンペーンパラメータが404になってはならない）。
- ディレクトリはサイトマップの静的ページに含め、フッターから常時リンクする。企業ページがサイトマップだけに載る孤立ページにならないようにするためである。
- ディレクトリのスナップショットは ADR-0016 の仕組みに乗せ、Data Cacheのキー空間は既存の `MAX_CACHEABLE_LISTING_PAGE` で上限を設ける。`/companies?page=<任意の整数>` は訪問者が作れるURLであり、上限がなければキャッシュがディスクへ無制限に書かれる。

## Consequences

企業ページのindex可否が募集の在庫から独立し、URLごとの評価が募集期をまたいで蓄積する。プロフィールを書く作業の見返りが、その企業が募集を出している期間だけに限られなくなる。ディレクトリは企業ページ群への恒久的な内部リンクであり、同時に「どんな企業が載っているか」を読者が一覧できる入口になる。

反面、現在の募集が0件の企業ページも検索結果に出る。そのページの「現在の募集」節は空であり、訪問者が募集を探して辿り着いた場合は過去の募集と公式サイトへの導線だけが残る。これは ADR-0017 が想定した表示（`companyMetadata` は「現在掲載中の募集はありません。」を返す）の範囲内だが、検索結果からの期待値とのずれは残る。プロフィールの質が低ければ薄いページがindexされる点も変わらず、運営者のレビューに委ねられる。

`lastmod` は全募集を対象にしても、締切通過そのものは捉えられない。締切が過ぎた日にページ内容は変わるが、行は更新されないためである。巻き戻りを避けることを優先し、この鮮度のずれは許容する。

ADR-0017 のうち、プロフィールの構造・最小文字数・MCP限定の書き込み経路・企業統合時の扱いは変更しない。

## Code anchors

- `backend/app/services/company_pages.py` の `_openings_aggregate` / `list_indexable_companies` / `company_detail_dict`
- `backend/app/api/companies.py`
- `frontend/lib/seo.ts` の `companyIsIndexable`
- `frontend/app/companies/page.tsx`
- `frontend/lib/seo-data.ts` の `loadCompanyDirectorySnapshot`
- `frontend/lib/sitemap.ts`
- `frontend/lib/structured-data.ts` の `companyDirectoryStructuredData`
- `backend/tests/test_company_pages.py`, `frontend/lib/seo.test.ts`, `frontend/app/sitemap.test.ts`
