# ADR-0015: 公開URLを正規化し、単一意図のカテゴリだけをindex対象にする

- Status: Accepted
- Scope: 公開ホスト、募集詳細URL、一覧の検索インデックス、サイトマップ

## Context

募集詳細は内部UUIDと8文字の公開コードのどちらでも取得でき、公開ホストもapexと`www`の両方が同じ内容を返せた。内部リンクがUUID、サイトマップが公開コードを使うと、同じ募集に複数のクロール可能URLと相反する正規化シグナルが生じる。

一覧は検索、並び替え、表示形式、複数ファセットをURLで表現する。すべてをindex対象にすると、ほぼ同じ内容の組み合わせが増える。一方、すべてを除外すると、業界、職種、卒業年度など明確な検索意図を持つ入口まで失う。

## Decision

- 公開originは`NEXT_PUBLIC_SITE_URL`のoriginを正本にし、`www`はapexへ308で転送する。
- 募集詳細のcanonicalは`/opportunities/{public_code}`とする。内部リンクとサイトマップも公開コードを使い、旧UUID URLは描画前に308転送する。
- 募集予定・募集中・通年募集のうち締切前または締切未定の詳細だけをindex対象にする。終了済み詳細は参照可能なまま`noindex, follow`にする。
- 自由検索、並び替え、非既定status、複数ファセット、範囲外ページは`noindex, follow`にする。
- 業界、業種、職種、募集種別、開催形式、卒業年度は、単一ファセットかつ最低件数を満たす場合だけindex対象にする。カテゴリには説明とHTMLリンクのディレクトリを置く。
- サイトマップは実行時に現在の募集予定・募集中・通年募集データから生成し、公開コードURLだけを含める。カテゴリ件数は一覧と同じ募集中データから集計する。

## Consequences

重複URLの評価と計測を一つに集約し、任意の絞り込み組み合わせを増やさずに検索意図のある入口を提供できる。旧UUIDアクセスでは内部APIの参照が1回増えるが、canonical URLへの通常アクセスには増えない。カテゴリのindex可否は在庫件数で変わるため、Search ConsoleではURL総数ではなくcanonical URL群ごとの表示・順位を監視する。

## Code anchors

- `frontend/proxy.ts`
- `frontend/lib/site.ts`
- `frontend/lib/seo.ts`
- `frontend/app/page.tsx`
- `frontend/app/opportunities/[id]/page.tsx`
- `frontend/app/sitemap.ts`
- `relua.conf`
