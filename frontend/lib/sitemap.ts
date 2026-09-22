import type { MetadataRoute } from "next";

import { getAllIndexableCompanies, getAllOpportunities, getMasters } from "@/lib/api";
import { indexableFacetValues, listingPath, opportunityIsIndexable } from "@/lib/seo";
import { companyPath, opportunityPath, siteOrigin } from "@/lib/site";
import type { CompanySummary, Opportunity } from "@/lib/types";

const staticPages: MetadataRoute.Sitemap = [
  { url: "", changeFrequency: "daily", priority: 1 },
  { url: "/companies", changeFrequency: "weekly", priority: 0.6 },
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

/**
 * A company page changes whenever its openings do, not only when its profile is
 * edited, so the newer of the two timestamps is the honest last-modified date.
 */
function companyLastModified(company: CompanySummary) {
  return [company.updated_at, company.openings_updated_at]
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1) ?? company.updated_at;
}

/**
 * The sitemap protocol rejects a file outright past 50,000 URLs (or 50MB),
 * rather than indexing the URLs under the limit and dropping the rest, so a
 * single-file sitemap has no room to degrade gracefully once inventory crosses
 * that line. The standard answer is a sitemap index pointing at numbered child
 * sitemaps, which is what `chunkSitemapEntries` and `sitemapIndexXml` below
 * exist for.
 */
export const SITEMAP_URL_LIMIT = 50_000;

/**
 * Deliberately under `SITEMAP_URL_LIMIT`. The limit applies to a file as
 * served, and the 50MB ceiling can bite before the URL count does, so leaving
 * headroom means inventory growth between two crawls cannot push a child
 * sitemap over either bound.
 */
export const SITEMAP_CHUNK_SIZE = 45_000;

/**
 * An index may itself list at most `SITEMAP_URL_LIMIT` child sitemaps, so this
 * is the point where even the split representation runs out. At
 * `SITEMAP_CHUNK_SIZE` URLs per child that is over two billion URLs — far past
 * anything this service will hold — but refusing loudly beats emitting a
 * document search engines discard without telling anyone.
 */
export class SitemapTooLargeError extends Error {
  constructor(count: number) {
    super(
      `Sitemap has ${count} URLs, which does not fit in an index of `
      + `${SITEMAP_URL_LIMIT} child sitemaps at ${SITEMAP_CHUNK_SIZE} URLs each.`,
    );
    this.name = "SitemapTooLargeError";
  }
}

/** Split a full entry list into child-sitemap-sized pages, numbered from 1. */
export function chunkSitemapEntries(entries: MetadataRoute.Sitemap): MetadataRoute.Sitemap[] {
  if (entries.length > SITEMAP_URL_LIMIT * SITEMAP_CHUNK_SIZE) {
    throw new SitemapTooLargeError(entries.length);
  }
  // One empty page rather than none, so an empty dataset still produces a
  // valid `/sitemap.xml` instead of an index that lists nothing.
  if (entries.length === 0) return [[]];
  const pages: MetadataRoute.Sitemap[] = [];
  for (let index = 0; index < entries.length; index += SITEMAP_CHUNK_SIZE) {
    pages.push(entries.slice(index, index + SITEMAP_CHUNK_SIZE));
  }
  return pages;
}

/** The path a child sitemap is served at. Page numbers are 1-based. */
export function childSitemapPath(page: number) {
  return `/sitemaps/${page}.xml`;
}

function newestLastModified(entries: MetadataRoute.Sitemap) {
  return entries
    .map((entry) => (entry.lastModified instanceof Date
      ? entry.lastModified.toISOString()
      : entry.lastModified))
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);
}

/** Render the parent index that points at every child sitemap. */
export function sitemapIndexXml(pages: MetadataRoute.Sitemap[], base = siteOrigin()) {
  const body = pages.map((entries, index) => {
    const lastModified = newestLastModified(entries);
    return [
      "<sitemap>",
      `<loc>${escapeXml(`${base}${childSitemapPath(index + 1)}`)}</loc>`,
      lastModified ? `<lastmod>${escapeXml(lastModified)}</lastmod>` : "",
      "</sitemap>",
    ].filter(Boolean).join("\n");
  }).join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${body}\n</sitemapindex>\n`;
}

/** Fetch a complete, internally consistent sitemap dataset. */
export async function getSitemapEntries(): Promise<MetadataRoute.Sitemap> {
  const base = siteOrigin();
  const [opportunities, masters, companies] = await Promise.all([
    getAllOpportunities(["status-01", "status-02", "status-04"]),
    getMasters(),
    // The API applies the same "has a written profile" rule the pages use for
    // robots, so this list and companyIsIndexable cannot disagree.
    getAllIndexableCompanies(),
  ]);
  const indexableOpportunities = opportunities.filter(opportunityIsIndexable);
  const activeOpportunities = indexableOpportunities.filter(
    (item) => item.recruitment_status.slug === "status-02",
  );
  const categoryPages = categorySitemapEntries(base, activeOpportunities, indexableFacetValues(masters));

  const entries = [
    ...staticPages.map((page) => ({ ...page, url: `${base}${page.url}` })),
    ...categoryPages,
    ...companies.map((company) => ({
      url: `${base}${companyPath(company.public_code)}`,
      lastModified: companyLastModified(company),
      changeFrequency: "weekly" as const,
      priority: 0.6,
    })),
    ...indexableOpportunities.map((opportunity) => ({
      url: `${base}${opportunityPath(opportunity.public_code)}`,
      lastModified: latestUpdate(opportunity),
      changeFrequency: "weekly" as const,
      priority: 0.8,
    })),
  ];

  return entries;
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
