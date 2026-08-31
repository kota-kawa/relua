import Link from "next/link";

import { indexableFacetValues, listingPath, type IndexableFacetKey } from "@/lib/seo";
import type { Masters } from "@/lib/types";

const GROUPS: { key: IndexableFacetKey; label: string }[] = [
  { key: "industry", label: "業界" },
  { key: "sector", label: "業種" },
  { key: "job_category", label: "職種" },
  { key: "event_type", label: "募集種別" },
  { key: "event_format", label: "開催形式" },
  { key: "graduation_year", label: "卒業年度" },
];

export function CategoryDirectory({ masters }: { masters: Masters }) {
  const facets = indexableFacetValues(masters);
  return (
    <section className="category-directory" aria-labelledby="category-directory-heading">
      <div className="shell">
        <p className="eyebrow">BROWSE BY CATEGORY</p>
        <h2 id="category-directory-heading">条件から募集を探す</h2>
        <p className="category-directory-lead">気になる業界・職種・参加形式から、現在応募できる募集へ移動できます。</p>
        <div className="category-directory-groups">
          {GROUPS.map((group) => {
            const entries = facets.filter((facet) => facet.key === group.key);
            if (!entries.length) return null;
            return (
              <section key={group.key}>
                <h3>{group.label}</h3>
                <ul>
                  {entries.map((facet) => (
                    <li key={facet.slug}>
                      <Link href={listingPath(facet)}>{facet.label}</Link>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      </div>
    </section>
  );
}
