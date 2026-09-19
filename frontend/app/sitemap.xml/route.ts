import { chunkSitemapEntries, getSitemapEntries, sitemapIndexXml, sitemapXml } from "@/lib/sitemap";

// Sitemap data must be obtained at request time. A build-time fallback could
// otherwise remain deployed after an API outage and silently hide URLs.
export const dynamic = "force-dynamic";

const SITEMAP_RETRY_AFTER_SECONDS = 300;
/**
 * `force-dynamic` means every request re-runs `getSitemapEntries()`, which
 * itself fans out one internal request per opportunity/company page. Without
 * a shared-cache header, anyone can repeat that fan-out at will simply by
 * requesting this URL in a loop. `s-maxage` lets a CDN or reverse proxy in
 * front of this route answer repeats from its own cache for an hour while
 * `stale-while-revalidate` keeps serving the previous body during that
 * revalidation, so crawlers still see a document this fresh without the
 * origin doing the fan-out on every single hit.
 */
const SITEMAP_CACHE_CONTROL = "public, s-maxage=3600, stale-while-revalidate=86400";

export async function GET() {
  try {
    const pages = chunkSitemapEntries(await getSitemapEntries());
    // Below the per-file limit there is nothing to gain from an index, and a
    // plain urlset keeps crawlers one request away from the URLs. Past it, the
    // same route becomes the index the protocol expects, so the sitemap URL
    // published in robots.txt never has to change.
    const body = pages.length === 1 ? sitemapXml(pages[0]) : sitemapIndexXml(pages);
    return new Response(body, {
      headers: { "Content-Type": "application/xml; charset=utf-8", "Cache-Control": SITEMAP_CACHE_CONTROL },
    });
  } catch (error) {
    console.error("sitemap generation failed", error instanceof Error ? error.message : error);
    return new Response("Sitemap temporarily unavailable\n", {
      status: 503,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": "text/plain; charset=utf-8",
        "Retry-After": String(SITEMAP_RETRY_AFTER_SECONDS),
      },
    });
  }
}
