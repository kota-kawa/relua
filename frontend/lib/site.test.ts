import { afterEach, describe, expect, it, vi } from "vitest";

import { absoluteUrl, companyPath, opportunityPath, siteOrigin } from "./site";

const originalSiteUrl = process.env.NEXT_PUBLIC_SITE_URL;

afterEach(() => {
  if (originalSiteUrl === undefined) delete process.env.NEXT_PUBLIC_SITE_URL;
  else process.env.NEXT_PUBLIC_SITE_URL = originalSiteUrl;
  vi.unstubAllEnvs();
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

  it("builds company paths from the public code, never the internal id", () => {
    expect(companyPath("CMPNY001")).toBe("/companies/CMPNY001");
    expect(companyPath("x/y")).toBe("/companies/x%2Fy");
  });
});

describe("production origin guard", () => {
  it("refuses to serve the localhost default in a production runtime", () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    vi.stubEnv("NODE_ENV", "production");
    expect(() => siteOrigin()).toThrow(/NEXT_PUBLIC_SITE_URL must be set/);
  });

  it("still returns a configured origin in production", () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.net";
    vi.stubEnv("NODE_ENV", "production");
    expect(siteOrigin()).toBe("https://relua.net");
  });

  it("allows the localhost default outside production, e.g. tests and dev", () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    expect(siteOrigin()).toBe("http://localhost:3100");
  });

  it("does not fail a production build itself, only the runtime that serves it", () => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PHASE", "phase-production-build");
    expect(siteOrigin()).toBe("http://localhost:3100");
  });
});
