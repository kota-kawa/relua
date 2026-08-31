import { afterEach, describe, expect, it } from "vitest";

import type { Opportunity } from "./types";
import { listingStructuredData, opportunityStructuredData, siteStructuredData } from "./structured-data";

const originalSiteUrl = process.env.NEXT_PUBLIC_SITE_URL;
const item = {
  id: "uuid-1",
  public_code: "ABC12345",
  company: { id: 1, name: "テスト株式会社" },
  event_name: "28卒 本選考",
  description: "募集内容です。",
  homepage_url: "https://company.example/",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-02T00:00:00Z",
  source_checked_at: "2026-08-03T00:00:00Z",
} as Opportunity;

afterEach(() => {
  if (originalSiteUrl === undefined) delete process.env.NEXT_PUBLIC_SITE_URL;
  else process.env.NEXT_PUBLIC_SITE_URL = originalSiteUrl;
});

describe("structured data", () => {
  it("uses stable IDs on the canonical site origin", () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example/ignored";
    expect(siteStructuredData()).toMatchObject({
      "@graph": [
        { "@id": "https://relua.example/#organization", url: "https://relua.example" },
        { "@id": "https://relua.example/#website", url: "https://relua.example" },
      ],
    });
  });

  it("describes the canonical public-code detail and latest visible change", () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    const data = opportunityStructuredData(item);
    expect(data).toMatchObject({
      "@graph": [
        {
          "@type": "BreadcrumbList",
          itemListElement: [
            { item: "https://relua.example" },
            { item: "https://relua.example/opportunities/ABC12345" },
          ],
        },
        {
          "@type": "WebPage",
          url: "https://relua.example/opportunities/ABC12345",
          dateModified: "2026-08-03T00:00:00Z",
        },
      ],
    });
  });

  it("links every listing entry to its canonical public code", () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    expect(listingStructuredData([item], 2, 12)).toMatchObject({
      itemListElement: [{ position: 13, url: "https://relua.example/opportunities/ABC12345" }],
    });
  });
});
