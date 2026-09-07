const DEVELOPMENT_ORIGIN = "http://localhost:3100";

/** The one public origin used by metadata, sitemaps, structured data, and links. */
export function siteOrigin() {
  return new URL(process.env.NEXT_PUBLIC_SITE_URL ?? DEVELOPMENT_ORIGIN).origin;
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
