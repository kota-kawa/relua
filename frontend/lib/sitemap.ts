import type { MetadataRoute } from "next";

import { getAllOpportunities, getMasters } from "@/lib/api";
import { indexableFacetValues, listingPath, opportunityIsIndexable } from "@/lib/seo";
import { opportunityPath, siteOrigin } from "@/lib/site";
import type { Opportunity } from "@/lib/types";

const staticPages: MetadataRoute.Sitemap = [
  { url: "", changeFrequency: "daily", priority: 1 },
  { url: "/about", changeFrequency: "yearly", priority: 0.5 },
  { url: "/terms", changeFrequency: "yearly", priority: 0.3 },
  { url: "/policy", changeFrequency: "yearly", priority: 0.3 },
];

function opportunityFacetSlugs(item: Opportunity, key: string) {
  switch (key) {
    case "industry": return [item.industry.slug];
    case "sector": return [item.sector.slug];
    case "job_category": return item.job_categories.map((value) => value.slug);
    case "event_type": return [item.event_type.slug];
    case "event_format": return [item.event_format.slug];
    case "graduation_year": return item.graduation_years.map((value) => value.slug);
    default: return [];
  }
}

function categorySitemapEntries(
  base: string,
  opportunities: Opportunity[],
  categories: ReturnType<typeof indexableFacetValues>,
): MetadataRoute.Sitemap {
  return categories.flatMap((facet) => {
    const total = opportunities.reduce(
      (count, item) => count + (opportunityFacetSlugs(item, facet.key).includes(facet.slug) ? 1 : 0),
      0,
    );
    // Inventory is no longer compared with a moving 5/8 item threshold. A
    // normal result is enough; a normal zero-result category is omitted and
    // the page itself returns 404.
    if (total === 0) return [];
    return [{
      url: `${base}${listingPath(facet)}`,
      changeFrequency: "daily" as const,
      priority: 0.7,
    }];
  });
}

function latestUpdate(opportunity: Opportunity) {
  return [opportunity.updated_at, opportunity.source_checked_at]
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1) ?? opportunity.updated_at;
}

/** Fetch a complete, internally consistent sitemap dataset. */
export async function getSitemapEntries(): Promise<MetadataRoute.Sitemap> {
  const base = siteOrigin();
  const [opportunities, masters] = await Promise.all([
    getAllOpportunities(["status-01", "status-02", "status-04"]),
    getMasters(),
  ]);
  const indexableOpportunities = opportunities.filter(opportunityIsIndexable);
  const activeOpportunities = indexableOpportunities.filter(
    (item) => item.recruitment_status.slug === "status-02",
  );
  const categoryPages = categorySitemapEntries(base, activeOpportunities, indexableFacetValues(masters));

  return [
    ...staticPages.map((page) => ({ ...page, url: `${base}${page.url}` })),
    ...categoryPages,
    ...indexableOpportunities.map((opportunity) => ({
      url: `${base}${opportunityPath(opportunity.public_code)}`,
      lastModified: latestUpdate(opportunity),
      changeFrequency: "weekly" as const,
      priority: 0.8,
    })),
  ];
}

function escapeXml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

export function sitemapXml(entries: MetadataRoute.Sitemap) {
  const body = entries.map((entry) => {
    const lastModified = entry.lastModified instanceof Date
      ? entry.lastModified.toISOString()
      : entry.lastModified;
    return [
      "<url>",
      `<loc>${escapeXml(entry.url)}</loc>`,
      lastModified ? `<lastmod>${escapeXml(String(lastModified))}</lastmod>` : "",
      entry.changeFrequency ? `<changefreq>${entry.changeFrequency}</changefreq>` : "",
      entry.priority !== undefined ? `<priority>${entry.priority}</priority>` : "",
      "</url>",
    ].filter(Boolean).join("\n");
  }).join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</urlset>\n`;
}
