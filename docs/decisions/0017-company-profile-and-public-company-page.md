# ADR-0017: 企業の事業内容を最小文字数付きの構造でMCPだけで記録し、公開コードの企業ページで見せる

- Status: Accepted
- Scope: 企業データモデル、企業ページの公開URLとindex、企業プロフィールの書き込み経路
- Amended by: [ADR-0023](./0023-company-pages-indexed-on-profile-alone.md)（index条件から現在の募集を外し、`lastmod` の基準を広げた）
- Amended by: [ADR-0025](./0025-batch-company-profile-updates.md)（企業ごとの更新日時照合・結果を持つ一括更新を追加した）

## Context

企業は名前・別名・業界分類しか持たず、募集詳細の企業名は文字列だった。閲覧者は「この会社が何をしているのか」を知るために外部検索へ戻るしかなく、同じ企業の複数募集をまとめて見る入口もなかった。

企業情報の入力元は運営者が確認した企業自身のページである。閲覧者が投稿する経路はなく、公開画面に書き込みフォームを作る理由もない。一方で、企業単位のページを無条件にindex対象にすると、名前と空のセクションしかないページが企業数だけ増える。

自由記述1本を「事業内容」として置くだけでは、企業ページが閲覧者の役に立つ保証がない。文字数の下限がなければ一文の説明でも登録でき、書き手への案内文だけでは分量も網羅範囲も担保できない。数百文字を1つの段落として出せば、今度は読み通せない塊になる。

過去には `opportunities.company_rating` を追加したが、検証できない企業単位の評価は保存しないという判断で [ADR-0005 以前の migration](../../backend/alembic/versions/20260806_0005_drop_company_rating.py) が削除している。

## Decision

- `companies` に `public_code`（8文字Crockford base32）、プロフィールの4列、`updated_at` を追加する。公開URLは `/companies/{public_code}` とし、内部の整数IDは公開しない。募集詳細と同じ [ADR-0016](./0016-seo-outage-resilience-and-reviewed-facets.md) の公開コード方針に合わせる。
- プロフィールは1つの自由記述ではなく、役割の違う4項目で持つ。`business_summary`（30〜200文字、何をしている会社かを言い切る1〜2文）、`description`（300〜4000文字、空行で段落を区切る本文）、`business_areas`（1〜6件、各事業の名称と60〜400文字の説明）、`website_url`。
- 各項目の最小文字数を入力検証で強制する。案内文だけでは分量を担保できないため、一言だけの登録は書き込みの入口で拒否する。
- 企業ページは項目ごとに表示を分ける。一言説明はheroの導入文、本文は段落に分割、主な事業は番号付きの見出しブロックとする。読み手が全体像を掴む順序と、文章の構造を一致させる。
- プロフィールの書き込みはMCPの `update_company_profile` だけとする。認証必須、`request_id` で冪等化し、監査ログに記録する。REST・画面からは書けない。
- 書き込みは部分更新とする。省略した項目は現在値を維持し、`null` の明示だけが削除である。冪等化ハッシュは送られたキーの集合を含むため、「省略」と「明示的な削除」は別操作として区別される。`business_areas` だけは業界分類と同じ全置換とする。事業の一覧は集合として意味を持ち、1件だけ差し替える操作に意味がないためである。
- 説明を確認した企業自身のページを `source_url` として必須にし、監査ログの `source_url` に残す。列は増やさない。[ADR-0013](./0013-official-source-allowlist-and-check-evidence.md) の確認証跡と同じ扱いで、求人・口コミサイトのURLは拒否する。
- 保存するのは事業の内容という事実だけで、将来性・働きやすさ・優良かどうかといった評価は入力仕様として禁止する。`company_rating` を削除した判断を維持する。
- 企業ページは、`business_summary` と `description` の両方が登録済みで、かつ現在の募集（募集予定・募集中・通年募集で締切前または未定）が1件以上ある企業だけをindex対象にする。片方だけでは見出しの下がほぼ空になるため両方を要求する。それ以外は参照可能なまま `noindex, follow` とする。この条件は `GET /api/v1/companies?indexable=true` が正本で、サイトマップも同じ一覧から作るため、ページのrobotsと収録範囲が食い違わない。
- 企業ページの `lastmod` と `dateModified` は、プロフィールの `updated_at` と現在の募集の最新 `updated_at` の新しい方とする。`updated_at` はプロフィール編集でしか動かないため、募集の増減による内容変化を単独では表せない。
- 企業統合では統合先のプロフィールを優先し、統合先が未登録の項目だけ統合元から引き継ぐ。統合元の `public_code` は物理削除に伴い404になる。
- 企業名リンクは募集詳細ページ（heroの企業名と「同じ企業の他の募集」）にだけ置く。一覧カードは全面が募集詳細への stretched link であり、企業リンクを重ねるとカード内に入れ子の操作対象を作ることになる。

## Consequences

閲覧者は募集から企業へ辿り、事業内容と現在・過去の募集を1ページで確認できる。最小文字数を強制したため、登録された企業ページには必ず読むに足る分量がある。index対象を「一言説明と本文があり、募集がある」に限ったため、企業マスタに名前だけ存在する数百社は検索対象を増やさない。

反面、1社のプロフィールを書く作業は重くなる。公式サイトの会社概要・事業紹介・IR資料を読んでから300文字以上をまとめる必要があり、片手間に埋められる項目ではない。網羅より分量を優先して薄い文章を長く書けば下限は通るため、内容の質は運営者のレビューに委ねられる。企業ページのindex可否は募集の在庫でも変わるため、締切通過の直後は最長1時間のスナップショット有効期間だけ古い判定が残り得る（募集詳細と同じ性質）。プロフィールを持つ企業を増やす作業はMCP経由の運用作業になり、公開画面から編集する経路は存在しない。

## Code anchors

- `backend/app/models.py` の `Company`
- `backend/alembic/versions/20260907_0014_add_company_profile.py`
- `backend/app/services/companies.py` の `update_company_profile` / `get_company_by_public_code`
- `backend/app/services/company_pages.py`
- `backend/app/api/companies.py`
- `backend/app/mcp_server.py` の `update_company_profile_tool`
- `backend/app/schemas.py` の `CompanyProfileUpdateRequest` と各ガイダンス定数
- `frontend/app/companies/[code]/page.tsx`
- `frontend/lib/seo.ts` の `companyProfileIsComplete` / `companyIsIndexable` / `companyMetadata`
- `frontend/lib/sitemap.ts`
- `backend/tests/test_company_pages.py`, `backend/tests/test_companies.py`
