import { afterEach, describe, expect, it, vi } from "vitest";

import { NextRequest } from "next/server";

import { canonicalHostUrl, legacyOpportunityId, proxy } from "./proxy";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL;

afterEach(() => {
  vi.unstubAllGlobals();
  if (siteUrl === undefined) delete process.env.NEXT_PUBLIC_SITE_URL;
  else process.env.NEXT_PUBLIC_SITE_URL = siteUrl;
});

describe("legacy opportunity URL matching", () => {
  it("matches internal UUID detail paths", () => {
    expect(legacyOpportunityId("/opportunities/e87f7f74-b5da-4b14-bc9b-5302146cd87d"))
      .toBe("e87f7f74-b5da-4b14-bc9b-5302146cd87d");
  });

  it("leaves canonical public codes and unrelated paths alone", () => {
    expect(legacyOpportunityId("/opportunities/A8MFMKFD")).toBeNull();
    expect(legacyOpportunityId("/saved")).toBeNull();
  });
});

describe("canonical host matching", () => {
  it("preserves path and query while moving www to the configured apex host", () => {
    expect(canonicalHostUrl(
      "https://www.relua.example/opportunities/ABC12345?from=test",
      "www.relua.example",
      "https://relua.example",
    )?.toString()).toBe("https://relua.example/opportunities/ABC12345?from=test");
  });

  it("does not redirect the canonical or an unrelated host", () => {
    expect(canonicalHostUrl("https://relua.example/", "relua.example", "https://relua.example")).toBeNull();
    expect(canonicalHostUrl("https://other.example/", "other.example", "https://relua.example")).toBeNull();
  });
});

describe("legacy UUID proxy resolution", () => {
  const uuid = "e87f7f74-b5da-4b14-bc9b-5302146cd87d";

  it("redirects a UUID on www directly to the canonical public code URL", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ public_code: "ABC12345" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await proxy(new NextRequest(`https://www.relua.example/opportunities/${uuid}?from=legacy`));

    expect(response.status).toBe(308);
    expect(response.headers.get("location")).toBe("https://relua.example/opportunities/ABC12345");
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("returns 404 for an API-confirmed missing UUID", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })));
    const response = await proxy(new NextRequest(`https://relua.example/opportunities/${uuid}`));
    expect(response.status).toBe(404);
  });

  it.each([
    ["upstream failure", new Response(null, { status: 502 })],
    ["malformed payload", new Response("{}", { status: 200 })],
  ])("returns 503 for %s", async (_label, upstream) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(upstream));
    const response = await proxy(new NextRequest(`https://relua.example/opportunities/${uuid}`));
    expect(response.status).toBe(503);
  });

  it("returns 503 for a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connection reset")));
    const response = await proxy(new NextRequest(`https://relua.example/opportunities/${uuid}`));
    expect(response.status).toBe(503);
  });
});
