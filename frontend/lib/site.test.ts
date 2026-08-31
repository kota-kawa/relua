import { afterEach, describe, expect, it } from "vitest";

import { absoluteUrl, opportunityPath, siteOrigin } from "./site";

const originalSiteUrl = process.env.NEXT_PUBLIC_SITE_URL;

afterEach(() => {
  if (originalSiteUrl === undefined) delete process.env.NEXT_PUBLIC_SITE_URL;
  else process.env.NEXT_PUBLIC_SITE_URL = originalSiteUrl;
});

describe("canonical site URLs", () => {
  it("normalizes a configured origin and joins paths without double slashes", () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example/base/";
    expect(siteOrigin()).toBe("https://relua.example");
    expect(absoluteUrl("/sitemap.xml")).toBe("https://relua.example/sitemap.xml");
  });

  it("encodes public references in canonical opportunity paths", () => {
    expect(opportunityPath("x/y")).toBe("/opportunities/x%2Fy");
  });
});
