import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

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

/**
 * Mirrors the Next.js 16 Data Cache: an expired entry is returned as-is and
 * refreshed in the background, which is what turns a long-unvisited URL into a
 * request that has to decide what to do with an out-of-date snapshot.
 */
const cacheHarness = vi.hoisted(() => {
  const entries = new Map<string, { value: unknown; storedAt: number }>();
  let background: Promise<unknown>[] = [];
  return {
    reset: () => {
      entries.clear();
      background = [];
    },
    /** Let the background revalidations finish, as the server does per request. */
    settled: async () => {
      while (background.length) {
        const pending = background;
        background = [];
        await Promise.all(pending);
      }
    },
    unstableCache: (
      fn: (...args: unknown[]) => Promise<unknown>,
      keyParts: string[] = [],
      options: { revalidate?: number } = {},
    ) => async (...args: unknown[]) => {
      const key = JSON.stringify([keyParts, args]);
      const hit = entries.get(key);
      const revalidateMs = (options.revalidate ?? 0) * 1000;
      if (hit) {
        if (Date.now() - hit.storedAt > revalidateMs) {
          background.push(
            fn(...args)
              .then((value) => entries.set(key, { value, storedAt: Date.now() }))
              .catch(() => undefined),
          );
        }
        return hit.value;
      }
      const value = await fn(...args);
      entries.set(key, { value, storedAt: Date.now() });
      return value;
    },
  };
});

vi.mock("@/lib/api", () => api);
vi.mock("next/cache", () => ({ unstable_cache: cacheHarness.unstableCache }));

// React `cache` does not memoize outside a render, so every loader call below
// is an independent request. That makes the process-wide sharing visible here,
// but it also means the within-request sharing of metadata and body is not
// covered by these tests; `docs/knowledge/seo-debugging.md` covers it against a
// production build instead.

import {
  loadCompanySnapshot,
  loadListingSnapshot,
  loadOpportunitySnapshot,
  listingSnapshotIsCacheable,
  normalizeListingParams,
  seoSnapshotIsFresh,
  MAX_CACHEABLE_LISTING_PAGE,
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

describe("listing Data Cache eligibility", () => {
  it("admits only URLs that could enter the index", () => {
    expect(listingSnapshotIsCacheable({})).toBe(true);
    expect(listingSnapshotIsCacheable({ industry: "industry-01" })).toBe(true);
    // A search query, an unknown facet value, and a non-default sort are all
    // `noindex`; letting a visitor mint a Data Cache entry from any of them is
    // exactly the unbounded-disk-writes case this function exists to prevent.
    expect(listingSnapshotIsCacheable({ q: "engineer" })).toBe(false);
    expect(listingSnapshotIsCacheable({ industry: "no-such-industry" })).toBe(false);
    expect(listingSnapshotIsCacheable({ sort: "updated" })).toBe(false);
  });

  it("stops admitting pagination past the cacheable depth", () => {
    expect(listingSnapshotIsCacheable({ page: String(MAX_CACHEABLE_LISTING_PAGE) })).toBe(true);
    expect(listingSnapshotIsCacheable({ page: String(MAX_CACHEABLE_LISTING_PAGE + 1) })).toBe(false);
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
  const initialTime = Date.parse("2026-09-07T00:00:00Z");

  afterEach(async () => {
    await cacheHarness.settled();
    cacheHarness.reset();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  function listingApiIsHealthy() {
    api.getMasters.mockResolvedValue(masters);
    api.getOpportunities.mockResolvedValue(result);
  }

  it("serves the last complete listing snapshot through a failed refresh", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(initialTime);
    listingApiIsHealthy();
    const initial = await loadListingSnapshot({});
    expect(initial.fetchedAt).toBe(initialTime);

    vi.setSystemTime(initialTime + 61_000);
    api.getMasters.mockRejectedValue(new Error("temporary outage"));
    api.getOpportunities.mockRejectedValue(new Error("temporary outage"));
    const stale = await loadListingSnapshot({});
    expect(stale.fetchedAt).toBe(initialTime);
  });

  it("waits for fresh data instead of failing a request the API can answer", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(initialTime);
    listingApiIsHealthy();
    await loadListingSnapshot({});
    expect(api.getOpportunities).toHaveBeenCalledTimes(1);

    // The first visit after a quiet day: the Data Cache still holds the entry
    // and hands it back expired, so the page must refresh rather than fail.
    const arrival = initialTime + SEO_DATA_MAX_STALE_MS + 1;
    vi.setSystemTime(arrival);
    const refreshed = await loadListingSnapshot({});
    expect(refreshed.fetchedAt).toBe(arrival);
    // The blocking read joins the Data Cache's own refresh rather than adding one.
    expect(api.getOpportunities).toHaveBeenCalledTimes(2);

    // The refreshed value is what the next request reads.
    await cacheHarness.settled();
    const next = await loadListingSnapshot({});
    expect(next.fetchedAt).toBe(arrival);
    expect(api.getOpportunities).toHaveBeenCalledTimes(2);
  });

  it("fails the request when the snapshot is too old and the refresh also fails", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(initialTime);
    listingApiIsHealthy();
    await loadListingSnapshot({});

    vi.setSystemTime(initialTime + SEO_DATA_MAX_STALE_MS + 1);
    api.getMasters.mockRejectedValue(new Error("temporary outage"));
    api.getOpportunities.mockRejectedValue(new Error("temporary outage"));
    await expect(loadListingSnapshot({})).rejects.toThrow("temporary outage");

    listingApiIsHealthy();
    const recovered = await loadListingSnapshot({});
    expect(recovered.fetchedAt).toBe(initialTime + SEO_DATA_MAX_STALE_MS + 1);
  });

  it("propagates an outage when there is no snapshot to fall back to", async () => {
    api.getMasters.mockRejectedValue(new Error("cold outage"));
    api.getOpportunities.mockRejectedValue(new Error("cold outage"));
    await expect(loadListingSnapshot({ q: "cold" })).rejects.toThrow("cold outage");
  });

  it("collapses concurrent requests for one key into a single fetch", async () => {
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    api.getMasters.mockResolvedValue(masters);
    api.getOpportunities.mockImplementation(async () => {
      await gate;
      return result;
    });

    const pending = [loadListingSnapshot({ q: "same" }), loadListingSnapshot({ q: "same" })];
    release?.();
    const [first, second] = await Promise.all(pending);
    expect(first.fetchedAt).toBe(second.fetchedAt);
    expect(api.getOpportunities).toHaveBeenCalledTimes(1);
  });

  it("collapses a burst on one expired key into a single refresh", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(initialTime);
    listingApiIsHealthy();
    await loadListingSnapshot({});

    // The case sharedSnapshot exists for: an unvisited URL goes past the bound
    // and several crawlers arrive at once.
    const arrival = initialTime + SEO_DATA_MAX_STALE_MS + 1;
    vi.setSystemTime(arrival);
    const snapshots = await Promise.all(
      Array.from({ length: 5 }, () => loadListingSnapshot({})),
    );
    expect(snapshots.every((snapshot) => snapshot.fetchedAt === arrival)).toBe(true);
    expect(api.getOpportunities).toHaveBeenCalledTimes(2);
  });

  it("fails every caller of one expired key when the shared refresh fails", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(initialTime);
    listingApiIsHealthy();
    await loadListingSnapshot({});

    vi.setSystemTime(initialTime + SEO_DATA_MAX_STALE_MS + 1);
    api.getMasters.mockRejectedValue(new Error("temporary outage"));
    api.getOpportunities.mockRejectedValue(new Error("temporary outage"));
    const results = await Promise.allSettled(
      Array.from({ length: 3 }, () => loadListingSnapshot({})),
    );
    expect(results.map((entry) => entry.status)).toEqual(["rejected", "rejected", "rejected"]);
    expect(api.getOpportunities).toHaveBeenCalledTimes(2);
  });

  it("keeps a separate snapshot per search key", async () => {
    listingApiIsHealthy();
    await loadListingSnapshot({ industry: "industry-01" });
    await loadListingSnapshot({ industry: "industry-02" });
    expect(api.getOpportunities).toHaveBeenCalledTimes(2);
  });

  it("still serves one Data Cache entry for a repeated indexable listing", async () => {
    listingApiIsHealthy();
    await loadListingSnapshot({ industry: "industry-01" });
    await loadListingSnapshot({ industry: "industry-01" });
    expect(api.getOpportunities).toHaveBeenCalledTimes(1);
  });

  it("fetches a search query directly instead of writing it to the Data Cache", async () => {
    listingApiIsHealthy();
    await loadListingSnapshot({ q: "engineer" });
    await loadListingSnapshot({ q: "engineer" });
    // A cacheable key would collapse this to one call, as the previous test
    // shows; a `q`-bearing URL is already `noindex`, so each request re-runs
    // the search rather than occupying a permanent key on disk.
    expect(api.getOpportunities).toHaveBeenCalledTimes(2);
  });

  it("caches a primary 404 as null and can replace it after recovery", async () => {
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
    // Inside the stale window the cached 404 still answers this request while
    // the refresh runs behind it; the request after that sees the new record.
    expect((await loadOpportunitySnapshot("legacy-id")).item).toBeNull();
    await cacheHarness.settled();
    const recovered = await loadOpportunitySnapshot("legacy-id");
    expect(recovered.item).toEqual(item);
  });

  it("still answers 404 when a missing detail's snapshot is past the bound", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(initialTime);
    api.getOpportunity.mockRejectedValue(new api.ApiError(404, "missing"));
    api.getSameCompanyOpportunities.mockResolvedValue([]);
    expect((await loadOpportunitySnapshot("gone")).item).toBeNull();

    vi.setSystemTime(initialTime + SEO_DATA_MAX_STALE_MS + 1);
    const refreshed = await loadOpportunitySnapshot("gone");
    expect(refreshed.item).toBeNull();
    expect(refreshed.fetchedAt).toBe(initialTime + SEO_DATA_MAX_STALE_MS + 1);
  });
});

describe("company snapshot loader", () => {
  afterEach(async () => {
    await cacheHarness.settled();
    cacheHarness.reset();
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

  it("refreshes a company page whose snapshot went past the bound", async () => {
    const initialTime = Date.parse("2026-09-07T00:00:00Z");
    vi.useFakeTimers();
    vi.setSystemTime(initialTime);
    const company = { id: 1, public_code: "CMPNY001", name: "株式会社サンプル" };
    api.getCompany.mockResolvedValue(company);
    await loadCompanySnapshot("CMPNY001");

    const arrival = initialTime + SEO_DATA_MAX_STALE_MS + 1;
    vi.setSystemTime(arrival);
    const refreshed = await loadCompanySnapshot("CMPNY001");
    expect(refreshed.company).toEqual(company);
    expect(refreshed.fetchedAt).toBe(arrival);
  });

  it("caches a 404 as null but lets an outage fail the page", async () => {
    const initialTime = Date.parse("2026-09-07T00:00:00Z");
    vi.useFakeTimers();
    vi.setSystemTime(initialTime);
    api.getCompany.mockRejectedValue(new api.ApiError(404, "missing"));
    expect((await loadCompanySnapshot("NOSUCH01")).company).toBeNull();

    api.getCompany.mockRejectedValue(new Error("temporary outage"));
    await expect(loadCompanySnapshot("OTHER001")).rejects.toThrow("temporary outage");

    // A snapshot older than the stale window must not keep serving on its own.
    vi.setSystemTime(initialTime + SEO_DATA_MAX_STALE_MS + 1);
    await expect(loadCompanySnapshot("NOSUCH01")).rejects.toThrow("temporary outage");
  });
});
