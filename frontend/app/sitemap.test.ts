import { afterEach, describe, expect, it, vi } from "vitest";

const getAllOpportunities = vi.hoisted(() => vi.fn());
const getMasters = vi.hoisted(() => vi.fn());
const getOpportunities = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api", () => ({ getAllOpportunities, getMasters, getOpportunities }));

import sitemap from "@/app/sitemap";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL;

afterEach(() => {
  vi.resetAllMocks();
  if (siteUrl === undefined) delete process.env.NEXT_PUBLIC_SITE_URL;
  else process.env.NEXT_PUBLIC_SITE_URL = siteUrl;
});

describe("sitemap", () => {
  it("includes every opportunity detail page with its latest update", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    getAllOpportunities.mockResolvedValue([
      { public_code: "ABC12345", updated_at: "2026-08-01T10:00:00Z" },
      { public_code: "x/y", updated_at: "2026-08-02T10:00:00Z" },
    ]);

    await expect(sitemap()).resolves.toEqual(expect.arrayContaining([
      {
        url: "https://relua.example/opportunities/ABC12345",
        lastModified: "2026-08-01T10:00:00Z",
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

  it("returns static pages when opportunity retrieval is unavailable", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    getAllOpportunities.mockRejectedValue(new Error("API unavailable"));

    await expect(sitemap()).resolves.toEqual([
      { url: "https://relua.example", changeFrequency: "daily", priority: 1 },
      { url: "https://relua.example/about", changeFrequency: "yearly", priority: 0.5 },
      { url: "https://relua.example/terms", changeFrequency: "yearly", priority: 0.3 },
      { url: "https://relua.example/policy", changeFrequency: "yearly", priority: 0.3 },
    ]);
  });

  it("includes only sufficiently populated high-intent category pages", async () => {
    process.env.NEXT_PUBLIC_SITE_URL = "https://relua.example";
    getAllOpportunities.mockResolvedValue([]);
    getMasters.mockResolvedValue({
      industries: [{ id: 1, slug: "industry-01", name: "IT・通信" }],
      event_types: [{ id: 2, slug: "type-01", name: "インターン" }],
      graduation_years: [{ id: 3, slug: "grad-02", name: "27卒" }],
      sectors: [],
      event_formats: [],
      job_categories: [],
      degrees: [],
      recruitment_statuses: [],
    });
    getOpportunities.mockResolvedValue({ total: 10 });

    await expect(sitemap()).resolves.toEqual(expect.arrayContaining([
      { url: "https://relua.example/?industry=industry-01", changeFrequency: "daily", priority: 0.7 },
      { url: "https://relua.example/?event_type=type-01", changeFrequency: "daily", priority: 0.7 },
      { url: "https://relua.example/?graduation_year=grad-02", changeFrequency: "daily", priority: 0.7 },
    ]));
  });
});
