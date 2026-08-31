import type { MetadataRoute } from "next";

import { siteOrigin } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  const base = siteOrigin();
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/api/"] },
    sitemap: `${base}/sitemap.xml`,
    host: base,
  };
}
