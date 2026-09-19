const DEVELOPMENT_ORIGIN = "http://localhost:3100";

/**
 * `next build` inlines every `NEXT_PUBLIC_*` reference, so the check below is
 * deliberately skipped while building: the build is where the value is baked
 * in, CI builds without one, and failing there would only move the error to a
 * place that cannot know the deployment's origin anyway.
 */
function isProductionRuntime() {
  return process.env.NODE_ENV === "production" && process.env.NEXT_PHASE !== "phase-production-build";
}

/** The one public origin used by metadata, sitemaps, structured data, and links. */
export function siteOrigin() {
  const origin = new URL(process.env.NEXT_PUBLIC_SITE_URL || DEVELOPMENT_ORIGIN).origin;
  // A production server about to emit the development origin has lost its build
  // argument (frontend/Dockerfile defaults it to localhost), and nothing else
  // would say so: canonical URLs, OG urls, JSON-LD @id, robots.txt's Sitemap and
  // Host, and every sitemap <loc> would point at localhost while the build and
  // the tests still pass. Refusing to serve is recoverable; an index full of
  // unreachable URLs is not.
  if (origin === DEVELOPMENT_ORIGIN && isProductionRuntime()) {
    throw new Error(
      "NEXT_PUBLIC_SITE_URL must be set to the public origin: canonical URLs, robots.txt and the sitemap are built from it",
    );
  }
  return origin;
}

export function absoluteUrl(path: string) {
  return new URL(path, `${siteOrigin()}/`).toString();
}

/** Public codes, rather than internal UUIDs, are the canonical detail-page identity. */
export function opportunityPath(publicCode: string) {
  return `/opportunities/${encodeURIComponent(publicCode)}`;
}

/** Companies follow the same policy: the public code, never the internal row id. */
export function companyPath(publicCode: string) {
  return `/companies/${encodeURIComponent(publicCode)}`;
}
