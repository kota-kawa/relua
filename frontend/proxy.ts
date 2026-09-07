import { NextRequest, NextResponse } from "next/server";

import { opportunityPath, siteOrigin } from "@/lib/site";

const UUID_PATH = /^\/opportunities\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$/i;
const PUBLIC_CODE = /^[0-9A-HJKMNP-TV-Z]{8}$/i;
const configuredTimeout = Number(process.env.API_INTERNAL_TIMEOUT_MS ?? "10000");
const API_TIMEOUT_MS = Number.isFinite(configuredTimeout) && configuredTimeout > 0 ? configuredTimeout : 10000;

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
  const id = legacyOpportunityId(request.nextUrl.pathname);
  if (id) {
    const baseUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
    const internalToken = process.env.API_INTERNAL_TOKEN ?? "local-development-internal-token";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
    try {
      const response = await fetch(`${baseUrl}/api/v1/opportunities/${encodeURIComponent(id)}`, {
        cache: "no-store",
        signal: controller.signal,
        headers: { Accept: "application/json", "X-Internal-API-Token": internalToken },
      });
      if (response.status === 404) return new NextResponse(null, { status: 404 });
      if (!response.ok) return new NextResponse(null, { status: 503 });
      const item = await response.json() as { public_code?: unknown };
      if (typeof item.public_code !== "string" || !PUBLIC_CODE.test(item.public_code)) {
        return new NextResponse(null, { status: 503 });
      }
      // Construct the target from the configured canonical origin and omit
      // query parameters, matching the existing UUID URL policy.
      return NextResponse.redirect(new URL(opportunityPath(item.public_code), siteOrigin()), 308);
    } catch {
      return new NextResponse(null, { status: 503 });
    } finally {
      clearTimeout(timeout);
    }
  }

  // UUID resolution runs before this branch so a www UUID reaches its final
  // public-code URL in one redirect rather than www -> apex -> public code.
  const hostRedirect = canonicalHostUrl(request.url, request.headers.get("host"));
  if (hostRedirect) return NextResponse.redirect(hostRedirect, 308);
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|favicon.png|relua-logo.png).*)"],
};
