import type { MetadataRoute } from "next";

import { getAllOpportunities, getMasters, getOpportunities } from "@/lib/api";
import { withDefaultOpenStatus } from "@/lib/format";
import {
  indexableFacetValues,
  listingPath,
  MIN_INDEXABLE_CATEGORY_RESULTS,
} from "@/lib/seo";

export const revalidate = 3600;

async function categorySitemapEntries(base: string): Promise<MetadataRoute.Sitemap> {
  try {
    const masters = await getMasters();
    const categories = indexableFacetValues(masters);
    const entries = await Promise.all(categories.map(async (facet) => {
      try {
        const result = await getOpportunities(withDefaultOpenStatus({ [facet.key]: facet.slug }));
        if (result.total < MIN_INDEXABLE_CATEGORY_RESULTS) return null;
        return {
          url: `${base}${listingPath(facet)}`,
          changeFrequency: "daily" as const,
          priority: 0.7,
        };
      } catch {
        return null;
      }
    }));
    return entries.filter((entry): entry is NonNullable<typeof entry> => entry !== null);
  } catch {
    return [];
  }
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3100";
  const staticPages: MetadataRoute.Sitemap = [
    { url: base, changeFrequency: "daily", priority: 1 },
    { url: `${base}/about`, changeFrequency: "yearly", priority: 0.5 },
    { url: `${base}/terms`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${base}/policy`, changeFrequency: "yearly", priority: 0.3 },
  ];

  try {
    const [opportunities, categoryPages] = await Promise.all([
      getAllOpportunities(),
      categorySitemapEntries(base),
    ]);
    return [
      ...staticPages,
      ...categoryPages,
      ...opportunities.map((opportunity) => ({
        url: `${base}/opportunities/${encodeURIComponent(opportunity.public_code)}`,
        lastModified: opportunity.updated_at,
        changeFrequency: "weekly" as const,
        priority: 0.8,
      })),
    ];
  } catch {
    return staticPages;
  }
}
