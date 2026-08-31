import { NextRequest, NextResponse } from "next/server";

import { opportunityPath, siteOrigin } from "@/lib/site";

const UUID_PATH = /^\/opportunities\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$/i;

export function legacyOpportunityId(pathname: string) {
  return UUID_PATH.exec(pathname)?.[1] ?? null;
}

export function canonicalHostUrl(requestUrl: string, host: string | null, preferredOrigin = siteOrigin()) {
  const preferred = new URL(preferredOrigin);
  if (host?.toLowerCase() !== `www.${preferred.host}`.toLowerCase()) return null;
  const target = new URL(requestUrl);
  target.protocol = preferred.protocol;
  target.host = preferred.host;
  return target;
}

/** Resolve old UUID detail links before React starts streaming a 200 response. */
export async function proxy(request: NextRequest) {
  const hostRedirect = canonicalHostUrl(request.url, request.headers.get("host"));
  if (hostRedirect) return NextResponse.redirect(hostRedirect, 308);

  const id = legacyOpportunityId(request.nextUrl.pathname);
  if (!id) return NextResponse.next();

  const baseUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
  const internalToken = process.env.API_INTERNAL_TOKEN ?? "local-development-internal-token";
  try {
    const response = await fetch(`${baseUrl}/api/v1/opportunities/${encodeURIComponent(id)}`, {
      cache: "no-store",
      headers: { Accept: "application/json", "X-Internal-API-Token": internalToken },
    });
    if (!response.ok) return NextResponse.next();
    const item = await response.json() as { public_code?: string };
    if (!item.public_code) return NextResponse.next();
    return NextResponse.redirect(new URL(opportunityPath(item.public_code), request.url), 308);
  } catch {
    // A temporary API failure must not make an otherwise valid detail URL fail.
    return NextResponse.next();
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|favicon.png|relua-logo.png).*)"],
};
