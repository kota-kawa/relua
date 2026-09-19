import type { MetadataRoute } from "next";

import { siteOrigin } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  const base = siteOrigin();
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/api/"] },
    sitemap: `${base}/sitemap.xml`,
    // The `Host` directive takes a bare hostname, not a URL with a scheme;
    // `siteOrigin()` returns the latter for building absolute links.
    host: new URL(base).host,
  };
}
