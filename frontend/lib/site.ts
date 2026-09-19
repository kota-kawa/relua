const DEVELOPMENT_ORIGIN = "http://localhost:3100";

/**
 * `next build` inlines every `NEXT_PUBLIC_*` reference, so a build is the one and only chance to
 * get this value right: whatever is in scope then is what the deployed bundle carries, and every
 * statically generated page has its canonical URL, OG image, Twitter image and JSON-LD `@id`
 * written into HTML that is then served as-is.
 *
 * Which is why the check below runs during the build too. It used to be skipped there, on the
 * reasoning that the build is where the value gets baked in — but that is exactly backwards. A
 * build without the variable produced `/about`, `/terms`, `/policy`, `/list`, `/saved`, `/import`
 * and `/robots.txt` as static artifacts full of `http://localhost:3100`, all of them serving 200
 * forever, while only the dynamic routes ever complained. Failing the build is recoverable in
 * seconds; an index and a set of social cards full of unreachable URLs is not.
 *
 * An explicit `NEXT_PUBLIC_SITE_URL=http://localhost:3100` is still honoured, so a local or CI
 * build only has to say so. It is the unset case — the one nobody meant — that stops.
 */
function requiresPublicOrigin() {
  return process.env.NODE_ENV === "production";
}

/** The one public origin used by metadata, sitemaps, structured data, and links. */
export function siteOrigin() {
  const configured = process.env.NEXT_PUBLIC_SITE_URL;
  if (!configured && requiresPublicOrigin()) {
    throw new Error(
      "NEXT_PUBLIC_SITE_URL must be set to the public origin: canonical URLs, robots.txt, the sitemap "
      + "and every social card are built from it, and a production build bakes it into static pages",
    );
  }
  return new URL(configured || DEVELOPMENT_ORIGIN).origin;
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
