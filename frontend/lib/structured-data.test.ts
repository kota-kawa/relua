import { afterEach, describe, expect, it } from "vitest";

import type { CompanyDetail, Opportunity } from "./types";
import { companyStructuredData, listingStructuredData, opportunityStructuredData, siteStructuredData } from "./structured-data";

const originalSiteUrl = process.env.NEXT_PUBLIC_SITE_URL;
const item = {
  id: "uuid-1",
  public_code: "ABC12345",
  company: { id: 1, name: "テスト株式会社", public_code: "CMPNY001", url: "https://relua.example/companies/CMPNY001" },
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

describe("company structured data", () => {
  const company = {
    id: 1,
    public_code: "CMPNY001",
    name: "テスト株式会社",
    business_summary: "業務システムの受託開発を行っている。",
    description: "販売管理と生産管理のシステムを個別に開発している。",
    business_areas: [{ name: "受託開発事業", description: "販売管理システムを開発している。" }],
    website_url: "https://company.example/",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-02T00:00:00Z",
    openings_updated_at: "2026-08-09T00:00:00Z",
  } as CompanyDetail;

  it("names the company as the page subject and takes the newer change date", () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    const data = companyStructuredData(company);
    expect(data["@graph"][1]).toMatchObject({
      "@id": "https://relua.example/companies/CMPNY001#webpage",
      url: "https://relua.example/companies/CMPNY001",
      dateModified: "2026-08-09T00:00:00Z",
      about: {
        "@type": "Organization",
        name: "テスト株式会社",
        url: "https://company.example/",
        knowsAbout: ["受託開発事業"],
      },
    });
  });

  it("omits an unknown homepage, profile and business list rather than inventing them", () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    const bare = { ...company, website_url: null, business_summary: null, description: null, business_areas: [] };
    // The graph entries are heterogeneous, so read the WebPage as a plain record.
    const page = companyStructuredData(bare)["@graph"][1] as Record<string, unknown>;
    expect(page.about).not.toHaveProperty("url");
    expect(page.about).not.toHaveProperty("knowsAbout");
    expect(page).not.toHaveProperty("description");
    expect(page.dateModified).toBe("2026-08-09T00:00:00Z");
  });
});
