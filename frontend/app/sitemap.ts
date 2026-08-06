import type { MetadataRoute } from "next";

import { getAllOpportunities } from "@/lib/api";

export const revalidate = 3600;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3100";
  const staticPages: MetadataRoute.Sitemap = [
    { url: base, changeFrequency: "daily", priority: 1 },
    { url: `${base}/about`, changeFrequency: "yearly", priority: 0.5 },
    { url: `${base}/terms`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${base}/policy`, changeFrequency: "yearly", priority: 0.3 },
  ];

  try {
    const opportunities = await getAllOpportunities();
    return [
      ...staticPages,
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
