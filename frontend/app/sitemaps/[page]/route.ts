import { chunkSitemapEntries, getSitemapEntries, sitemapXml } from "@/lib/sitemap";

// Same reasoning as the parent index: sitemap data must be obtained at request
// time so an API outage cannot leave a stale build-time document deployed.
export const dynamic = "force-dynamic";

const SITEMAP_RETRY_AFTER_SECONDS = 300;
const SITEMAP_CACHE_CONTROL = "public, s-maxage=3600, stale-while-revalidate=86400";

/**
 * A child sitemap of the index served at `/sitemap.xml`.
 *
 * Each child recomputes the whole dataset and then slices its own page. That
 * looks wasteful, but the alternative — caching the split in memory — would
 * let two children answer from different snapshots and disagree about which
 * page a URL belongs to, which is how URLs go missing from an index. The
 * shared-cache headers keep the repeated fan-out off the origin instead.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ page: string }> }) {
  const { page: rawPage } = await params;
  const page = Number(rawPage.replace(/\.xml$/, ""));
  if (!Number.isSafeInteger(page) || page < 1) {
    return new Response("Not found\n", {
      status: 404,
      headers: { "Cache-Control": "no-store", "Content-Type": "text/plain; charset=utf-8" },
    });
  }

  try {
    const pages = chunkSitemapEntries(await getSitemapEntries());
    const entries = pages[page - 1];
    // A page number past the end is a stale index entry, not an outage: answer
    // 404 so the crawler drops it rather than retrying it for hours.
    if (!entries) {
      return new Response("Not found\n", {
        status: 404,
        headers: { "Cache-Control": "no-store", "Content-Type": "text/plain; charset=utf-8" },
      });
    }
    return new Response(sitemapXml(entries), {
      headers: { "Content-Type": "application/xml; charset=utf-8", "Cache-Control": SITEMAP_CACHE_CONTROL },
    });
  } catch (error) {
    console.error("child sitemap generation failed", error instanceof Error ? error.message : error);
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
