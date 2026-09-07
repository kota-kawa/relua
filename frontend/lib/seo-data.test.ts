import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}), { virtual: true });

const api = vi.hoisted(() => ({
  getMasters: vi.fn(),
  getOpportunities: vi.fn(),
  getOpportunity: vi.fn(),
  getSameCompanyOpportunities: vi.fn(),
  getCompany: vi.fn(),
  ApiError: class extends Error {
    constructor(public status: number, message: string) {
      super(message);
    }
  },
}));

const cacheHarness = vi.hoisted(() => {
  const entries = new Map<string, { value: unknown; storedAt: number }>();
  return {
    clear: () => entries.clear(),
    unstableCache: (
      fn: (...args: unknown[]) => Promise<unknown>,
      keyParts: string[] = [],
      options: { revalidate?: number } = {},
    ) => async (...args: unknown[]) => {
      const key = JSON.stringify([keyParts, args]);
      const hit = entries.get(key);
      const revalidateMs = (options.revalidate ?? 0) * 1000;
      if (hit && Date.now() - hit.storedAt <= revalidateMs) return hit.value;
      try {
        const value = await fn(...args);
        entries.set(key, { value, storedAt: Date.now() });
        return value;
      } catch (error) {
        if (hit) return hit.value;
        throw error;
      }
    },
  };
});

vi.mock("@/lib/api", () => api);
vi.mock("next/cache", () => ({ unstable_cache: cacheHarness.unstableCache }));

import {
  loadCompanySnapshot,
  loadListingSnapshot,
  loadOpportunitySnapshot,
  normalizeListingParams,
  seoSnapshotIsFresh,
  SEO_DATA_MAX_STALE_MS,
} from "./seo-data";

describe("SEO data cache keys", () => {
  it("keeps the page's exact parameter semantics while omitting API-irrelevant keys", () => {
    const normalized = normalizeListingParams({ view: ["", "calendar"], unknown: "ignored" });
    expect(normalized.params).toEqual({ status: "status-02", view: ["", "calendar"] });
  });

  it("uses the same key when callers only differ in object property order", () => {
    expect(normalizeListingParams({ page: "2", industry: "industry-01" }).key)
      .toBe(normalizeListingParams({ industry: "industry-01", page: "2" }).key);
  });
});

describe("SEO snapshot age", () => {
  const now = Date.parse("2026-09-07T00:00:00Z");

  it("allows the one-hour boundary and rejects older or invalid timestamps", () => {
    expect(seoSnapshotIsFresh(now - SEO_DATA_MAX_STALE_MS, now)).toBe(true);
    expect(seoSnapshotIsFresh(now - SEO_DATA_MAX_STALE_MS - 1, now)).toBe(false);
    expect(seoSnapshotIsFresh(Number.NaN, now)).toBe(false);
  });
});

describe("SEO snapshot loaders", () => {
  const masters = {
    industries: [], sectors: [], event_types: [], event_formats: [],
    job_categories: [], graduation_years: [], degrees: [], recruitment_statuses: [],
  };
  const result = { items: [], total: 0, page: 1, per_page: 12, total_pages: 0 };

  afterEach(() => {
    cacheHarness.clear();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("serves the last complete listing snapshot through a failed refresh, then recovers", async () => {
    const initialTime = Date.parse("2026-09-07T00:00:00Z");
    vi.useFakeTimers();
    vi.setSystemTime(initialTime);
    api.getMasters.mockResolvedValue(masters);
    api.getOpportunities.mockResolvedValue(result);
    const initial = await loadListingSnapshot({});
    expect(initial.fetchedAt).toBe(initialTime);

    vi.setSystemTime(initialTime + 61_000);
    api.getMasters.mockRejectedValue(new Error("temporary outage"));
    api.getOpportunities.mockRejectedValue(new Error("temporary outage"));
    const stale = await loadListingSnapshot({});
    expect(stale.fetchedAt).toBe(initialTime);

    vi.setSystemTime(initialTime + SEO_DATA_MAX_STALE_MS + 1);
    await expect(loadListingSnapshot({})).rejects.toThrow("SEO data");

    api.getMasters.mockResolvedValue(masters);
    api.getOpportunities.mockResolvedValue(result);
    const recovered = await loadListingSnapshot({});
    expect(recovered.fetchedAt).toBe(initialTime + SEO_DATA_MAX_STALE_MS + 1);
  });

  it("caches a primary 404 as null and can replace it after recovery", async () => {
    const initialTime = Date.parse("2026-09-07T00:00:00Z");
    vi.useFakeTimers();
    vi.setSystemTime(initialTime);
    api.getOpportunity.mockRejectedValue(new api.ApiError(404, "missing"));
    api.getSameCompanyOpportunities.mockRejectedValue(new Error("related outage"));
    const missing = await loadOpportunitySnapshot("legacy-id");
    expect(missing.item).toBeNull();
    expect(missing.sameCompanyOpportunities).toEqual([]);

    vi.setSystemTime(initialTime + 61_000);
    const item = { id: "id", public_code: "ABC12345" };
    api.getOpportunity.mockResolvedValue(item);
    api.getSameCompanyOpportunities.mockResolvedValue([]);
    const recovered = await loadOpportunitySnapshot("legacy-id");
    expect(recovered.item).toEqual(item);
  });
});

describe("company snapshot loader", () => {
  afterEach(() => {
    cacheHarness.clear();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("normalizes the code so one cache entry serves either casing", async () => {
    const company = { id: 1, public_code: "CMPNY001", name: "株式会社サンプル" };
    api.getCompany.mockResolvedValue(company);

    expect((await loadCompanySnapshot("cmpny001")).company).toEqual(company);
    expect(api.getCompany).toHaveBeenCalledWith("CMPNY001");

    await loadCompanySnapshot("CMPNY001");
    expect(api.getCompany).toHaveBeenCalledTimes(1);
  });

  it("caches a 404 as null but lets an outage fail the page", async () => {
    const initialTime = Date.parse("2026-09-07T00:00:00Z");
    vi.useFakeTimers();
    vi.setSystemTime(initialTime);
    api.getCompany.mockRejectedValue(new api.ApiError(404, "missing"));
    expect((await loadCompanySnapshot("NOSUCH01")).company).toBeNull();

    api.getCompany.mockRejectedValue(new Error("temporary outage"));
    await expect(loadCompanySnapshot("OTHER001")).rejects.toThrow("temporary outage");

    // A snapshot older than the stale window must not keep serving.
    vi.setSystemTime(initialTime + SEO_DATA_MAX_STALE_MS + 1);
    await expect(loadCompanySnapshot("NOSUCH01")).rejects.toThrow();
  });
});
