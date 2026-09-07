import { getSitemapEntries, sitemapXml } from "@/lib/sitemap";

// Sitemap data must be obtained at request time. A build-time fallback could
// otherwise remain deployed after an API outage and silently hide URLs.
export const dynamic = "force-dynamic";

const SITEMAP_RETRY_AFTER_SECONDS = 300;

export async function GET() {
  try {
    const entries = await getSitemapEntries();
    return new Response(sitemapXml(entries), {
      headers: { "Content-Type": "application/xml; charset=utf-8" },
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
