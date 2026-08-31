import type { MetadataRoute } from "next";

import { getAllOpportunities, getMasters } from "@/lib/api";
import {
  indexableFacetValues,
  listingPath,
  minimumIndexableResults,
  opportunityIsIndexable,
} from "@/lib/seo";
import { opportunityPath, siteOrigin } from "@/lib/site";
import type { Opportunity } from "@/lib/types";

// The API is intentionally unavailable during an isolated frontend image build.
// Generate on request so a build-time fallback can never become the live map.
export const dynamic = "force-dynamic";

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
    if (total < minimumIndexableResults(facet.key)) return [];
    return [{
      url: `${base}${listingPath(facet)}`,
      changeFrequency: "daily" as const,
      priority: 0.7,
    }];
  });
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = siteOrigin();
  const staticPages: MetadataRoute.Sitemap = [
    { url: base, changeFrequency: "daily", priority: 1 },
    { url: `${base}/about`, changeFrequency: "yearly", priority: 0.5 },
    { url: `${base}/terms`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${base}/policy`, changeFrequency: "yearly", priority: 0.3 },
  ];

  const [opportunitiesResult, mastersResult] = await Promise.allSettled([
    getAllOpportunities(["status-01", "status-02", "status-04"]),
    getMasters(),
  ]);
  if (opportunitiesResult.status !== "fulfilled") {
    return staticPages;
  }
  const indexableOpportunities = opportunitiesResult.value.filter(opportunityIsIndexable);
  const categoryPages = mastersResult.status === "fulfilled"
    ? categorySitemapEntries(
        base,
        indexableOpportunities.filter((item) => item.recruitment_status.slug === "status-02"),
        indexableFacetValues(mastersResult.value),
      )
    : [];
  return [
    ...staticPages,
    ...categoryPages,
    ...indexableOpportunities.map((opportunity) => ({
      url: `${base}${opportunityPath(opportunity.public_code)}`,
      lastModified: [opportunity.updated_at, opportunity.source_checked_at]
        .filter((value): value is string => Boolean(value))
        .sort()
        .at(-1) ?? opportunity.updated_at,
      changeFrequency: "weekly" as const,
      priority: 0.8,
    })),
  ];
}
