import type { ListingFacet } from "@/lib/seo";

function facetPurpose(facet: ListingFacet) {
  switch (facet.key) {
    case "graduation_year":
      return `${facet.label}向けの応募対象をまとめています`;
    case "event_type":
      return `${facet.label}として募集されている機会をまとめています`;
    case "event_format":
      return `${facet.label}で参加できる募集をまとめています`;
    case "job_category":
      return `${facet.label}に関わる募集をまとめています`;
    case "sector":
    case "industry":
      return `${facet.label}に属する企業の募集をまとめています`;
  }
}

export function CategoryOverview({ facet, total }: { facet: ListingFacet; total: number }) {
  if (!facet.label) return null;
  return (
    <section className="category-overview" aria-labelledby="category-overview-heading">
      <div className="shell category-overview-inner">
        <div>
          <p className="eyebrow">CATEGORY GUIDE</p>
          <h2 id="category-overview-heading">{facet.label}の募集を比較する</h2>
        </div>
        <p>
          {facetPurpose(facet)}。現在応募できる募集は<strong>{total.toLocaleString("ja-JP")}件</strong>です。
          応募締切、対象学年、開催形式、職種を同じ基準で比較でき、各詳細ページから企業の公式情報を確認できます。
        </p>
      </div>
    </section>
  );
}
