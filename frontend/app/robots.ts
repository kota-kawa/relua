import type { MetadataRoute } from "next";

import { siteOrigin } from "@/lib/site";

/**
 * Evaluated per request, like the sitemap routes, so `siteOrigin()`'s
 * production guard can actually fire here.
 *
 * Statically generated, this file is rendered once during `next build` — the
 * one phase that guard deliberately skips, because the build is where
 * `NEXT_PUBLIC_*` gets inlined and CI builds without a public origin. A build
 * missing that variable therefore baked `Host: localhost:3100` and a localhost
 * `Sitemap:` into a static artifact that then served 200 forever, while every
 * dynamic route 500ed. The one file whose whole job is to tell crawlers where
 * the sitemap lives was the one file the guard could not reach.
 */
export const dynamic = "force-dynamic";

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
