import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getAllOpportunities = vi.hoisted(() => vi.fn());
const getMasters = vi.hoisted(() => vi.fn());
const getAllIndexableCompanies = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({ getAllOpportunities, getMasters, getAllIndexableCompanies }));

import { getSitemapEntries, sitemapXml } from "@/lib/sitemap";
import { GET } from "@/app/sitemap.xml/route";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL;

beforeEach(() => {
  // Most tests are about opportunities and categories; the company list only
  // matters where a test sets it explicitly.
  getAllIndexableCompanies.mockResolvedValue([]);
});

afterEach(() => {
  vi.resetAllMocks();
  if (siteUrl === undefined) delete process.env.NEXT_PUBLIC_SITE_URL;
  else process.env.NEXT_PUBLIC_SITE_URL = siteUrl;
});

describe("sitemap", () => {
  it("includes every opportunity detail page with its latest update", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    getMasters.mockResolvedValue({
      industries: [], sectors: [], event_types: [], event_formats: [],
      job_categories: [], graduation_years: [], degrees: [], recruitment_statuses: [],
    });
    getAllOpportunities.mockResolvedValue([
      { public_code: "ABC12345", updated_at: "2026-08-01T10:00:00Z", source_checked_at: "2026-08-03T10:00:00Z", recruitment_status: { slug: "status-02" } },
      { public_code: "x/y", updated_at: "2026-08-02T10:00:00Z", source_checked_at: null, recruitment_status: { slug: "status-02" } },
    ]);

    await expect(getSitemapEntries()).resolves.toEqual(expect.arrayContaining([
      {
        url: "https://relua.example/opportunities/ABC12345",
        lastModified: "2026-08-03T10:00:00Z",
        changeFrequency: "weekly",
        priority: 0.8,
      },
      {
        url: "https://relua.example/opportunities/x%2Fy",
        lastModified: "2026-08-02T10:00:00Z",
        changeFrequency: "weekly",
        priority: 0.8,
      },
    ]));
  });

  it("fails the whole sitemap when opportunity retrieval is unavailable", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    getAllOpportunities.mockRejectedValue(new Error("API unavailable"));

    await expect(getSitemapEntries()).rejects.toThrow("API unavailable");
  });

  it("includes allowlisted category pages with one or more active results", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    getAllOpportunities.mockResolvedValue(Array.from({ length: 10 }, (_, index) => ({
      public_code: `CODE000${index}`,
      updated_at: "2026-08-01T00:00:00Z",
      source_checked_at: null,
      recruitment_status: { slug: "status-02" },
      industry: { slug: "industry-01" },
      sector: { slug: "sector-1-01" },
      event_type: { slug: "type-01" },
      event_format: { slug: "format-01" },
      job_categories: [{ slug: "job-01" }],
      graduation_years: [{ slug: "grad-02" }],
    })));
    getMasters.mockResolvedValue({
      industries: [{ id: 1, slug: "industry-01", name: "IT・通信" }],
      event_types: [{ id: 2, slug: "type-01", name: "インターン" }],
      event_formats: [{ id: 4, slug: "format-01", name: "オンライン" }],
      job_categories: [{ id: 5, slug: "job-01", name: "ソフトウェアエンジニア" }],
      graduation_years: [{ id: 3, slug: "grad-02", name: "27卒" }],
      sectors: [{ id: 6, slug: "sector-1-01", name: "ソフトウェア", industry_id: 1 }],
      degrees: [],
      recruitment_statuses: [],
    });
    await expect(getSitemapEntries()).resolves.toEqual(expect.arrayContaining([
      { url: "https://relua.example/?industry=industry-01", changeFrequency: "daily", priority: 0.7 },
      { url: "https://relua.example/?event_type=type-01", changeFrequency: "daily", priority: 0.7 },
      { url: "https://relua.example/?graduation_year=grad-02", changeFrequency: "daily", priority: 0.7 },
      { url: "https://relua.example/?sector=sector-1-01", changeFrequency: "daily", priority: 0.7 },
      { url: "https://relua.example/?job_category=job-01", changeFrequency: "daily", priority: 0.7 },
      { url: "https://relua.example/?event_format=format-01", changeFrequency: "daily", priority: 0.7 },
    ]));
  });

  it("omits ended opportunities even when their status has not been refreshed", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    getMasters.mockResolvedValue({
      industries: [], sectors: [], event_types: [], event_formats: [],
      job_categories: [], graduation_years: [], degrees: [], recruitment_statuses: [],
    });
    getAllOpportunities.mockResolvedValue([
      {
        public_code: "EXPIRED1",
        updated_at: "2026-08-01T00:00:00Z",
        source_checked_at: null,
        deadline: "2020-01-01",
        recruitment_status: { slug: "status-02" },
      },
    ]);

    const entries = await getSitemapEntries();
    expect(entries.some((entry) => entry.url.endsWith("/opportunities/EXPIRED1"))).toBe(false);
  });

  it("fails the whole sitemap when the master catalog is unavailable", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    getMasters.mockRejectedValue(new Error("catalog unavailable"));
    getAllOpportunities.mockResolvedValue([
      {
        public_code: "ABC12345",
        updated_at: "2026-08-01T00:00:00Z",
        source_checked_at: null,
        deadline: null,
        recruitment_status: { slug: "status-02" },
      },
    ]);

    await expect(getSitemapEntries()).rejects.toThrow("catalog unavailable");
  });

  it("includes indexable company pages with the newer of profile and opening updates", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    getMasters.mockResolvedValue({
      industries: [], sectors: [], event_types: [], event_formats: [],
      job_categories: [], graduation_years: [], degrees: [], recruitment_statuses: [],
    });
    getAllOpportunities.mockResolvedValue([]);
    getAllIndexableCompanies.mockResolvedValue([
      { public_code: "CMPNY001", updated_at: "2026-08-01T00:00:00Z", openings_updated_at: "2026-08-09T00:00:00Z" },
      { public_code: "CMPNY002", updated_at: "2026-08-05T00:00:00Z", openings_updated_at: null },
    ]);

    await expect(getSitemapEntries()).resolves.toEqual(expect.arrayContaining([
      {
        url: "https://relua.example/companies/CMPNY001",
        lastModified: "2026-08-09T00:00:00Z",
        changeFrequency: "weekly",
        priority: 0.6,
      },
      {
        url: "https://relua.example/companies/CMPNY002",
        lastModified: "2026-08-05T00:00:00Z",
        changeFrequency: "weekly",
        priority: 0.6,
      },
    ]));
  });

  it("fails the whole sitemap when the company list is unavailable", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    getMasters.mockResolvedValue({
      industries: [], sectors: [], event_types: [], event_formats: [],
      job_categories: [], graduation_years: [], degrees: [], recruitment_statuses: [],
    });
    getAllOpportunities.mockResolvedValue([]);
    getAllIndexableCompanies.mockRejectedValue(new Error("companies unavailable"));

    await expect(getSitemapEntries()).rejects.toThrow("companies unavailable");
  });

  it("escapes XML values and serializes metadata", () => {
    expect(sitemapXml([{ url: "https://relua.example/?q=a&b=<c>", lastModified: new Date("2026-08-01T00:00:00Z"), changeFrequency: "daily", priority: 0.5 }]))
      .toContain("<loc>https://relua.example/?q=a&amp;b=&lt;c&gt;</loc>");
  });

  it("returns static pages for a confirmed empty inventory", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    getAllOpportunities.mockResolvedValue([]);
    getMasters.mockResolvedValue({
      industries: [], sectors: [], event_types: [], event_formats: [],
      job_categories: [], graduation_years: [], degrees: [], recruitment_statuses: [],
    });
    const response = await GET();
    expect(response.status).toBe(200);
    expect((await response.text()).match(/<url>/g)).toHaveLength(4);
  });

  it("returns 503 with retry headers for a sitemap outage", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    getAllOpportunities.mockRejectedValue(new Error("API unavailable"));
    const response = await GET();
    expect(response.status).toBe(503);
    expect(response.headers.get("retry-after")).toBe("300");
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
});
