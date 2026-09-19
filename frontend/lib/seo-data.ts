import "server-only";

import { unstable_cache } from "next/cache";
import { cache } from "react";

import {
  ApiError,
  getCompany,
  getMasters,
  getOpportunity,
  getOpportunities,
  getSameCompanyOpportunities,
} from "@/lib/api";
import { withDefaultOpenStatus } from "@/lib/format";
import { getListingSeo } from "@/lib/seo";
import type { CompanyDetail, Masters, Opportunity, OpportunityList, SearchParams } from "@/lib/types";

export const SEO_DATA_REVALIDATE_SECONDS = 60;
export const SEO_DATA_MAX_STALE_MS = 60 * 60 * 1000;
/**
 * How deep pagination is still worth a stored snapshot. The cached key space is
 * (reviewed category values + the bare listing) x this number, so the bound has
 * to exist; past it the page is still served, just fetched per request. Crawlers
 * spend their budget on the first pages of a category, which is what ADR-0018's
 * blocking refresh is protecting.
 */
export const MAX_CACHEABLE_LISTING_PAGE = 20;

export class SeoDataUnavailableError extends Error {
  constructor(message = "SEO data is temporarily unavailable") {
    super(message);
    this.name = "SeoDataUnavailableError";
  }
}

export type ListingSnapshot = {
  masters: Masters;
  result: OpportunityList;
  fetchedAt: number;
};

export type OpportunitySnapshot = {
  item: Opportunity | null;
  sameCompanyOpportunities: Opportunity[];
  fetchedAt: number;
};

export type CompanySnapshot = {
  company: CompanyDetail | null;
  fetchedAt: number;
};

/**
 * These are the values that affect the public listing response. Unknown query
 * keys are intentionally excluded because the API ignores them. The object
 * property order is fixed while each value's exact shape and order is kept so
 * cache-key normalization never changes API or SEO semantics.
 */
const LISTING_CACHE_KEYS = [
  "q",
  "status",
  "status_scope",
  "industry",
  "sector",
  "event_type",
  "event_format",
  "job_category",
  "graduation_year",
  "degree",
  "sort",
  "page",
  "view",
] as const;

function normalizedValues(params: SearchParams, key: string) {
  const value = params[key];
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

/** Apply the listing defaults and produce one stable primitive cache key. */
export function normalizeListingParams(params: SearchParams): { params: SearchParams; key: string } {
  const effective = withDefaultOpenStatus(params);
  const normalized: SearchParams = {};
  for (const key of LISTING_CACHE_KEYS) {
    const values = normalizedValues(effective, key);
    if (values.length === 0) continue;
    normalized[key] = values.length === 1 ? values[0] : values;
  }
  return { params: normalized, key: JSON.stringify(normalized) };
}

/**
 * Whether this listing URL may occupy a Data Cache entry.
 *
 * `unstable_cache` writes each distinct key to disk (`.next/cache/fetch-cache`)
 * and nothing evicts it, so the key space has to be one this site defines rather
 * than one a visitor can mint: `/?q=<random>` or `/?industry=<random>` repeated
 * in a loop would otherwise write unboundedly, each entry holding the masters
 * plus up to sixty opportunities, and re-run the full-text search besides.
 *
 * The rule reuses the index decision rather than inventing a second one: exactly
 * the URLs that can enter the index are cached, which is the set ADR-0018's
 * blocking refresh exists for. Everything else — a search query, an unknown
 * facet value, an arbitrary filter combination, a sort — is already `noindex`,
 * so it is fetched directly and only deduplicated within its own request.
 */
export function listingSnapshotIsCacheable(normalized: SearchParams) {
  if (!getListingSeo(normalized).index) return false;
  const pages = normalizedValues(normalized, "page");
  // `index` above already rejected anything that is not a single positive
  // integer, so this is only the depth check.
  return pages.length === 0 || Number(pages[0]) <= MAX_CACHEABLE_LISTING_PAGE;
}

export function seoSnapshotIsFresh(fetchedAt: number, now = Date.now()) {
  return Number.isFinite(fetchedAt) && now - fetchedAt <= SEO_DATA_MAX_STALE_MS;
}

/**
 * The last line of the freshness bound rather than the outage path: an outage
 * surfaces as the API's own error. This only fires if a just-completed refresh
 * still carries an out-of-date timestamp, which today means a backwards clock
 * jump or a future fetcher that returns something it did not fetch.
 */
function assertFresh<T extends { fetchedAt: number }>(snapshot: T): T {
  if (!seoSnapshotIsFresh(snapshot.fetchedAt)) {
    throw new SeoDataUnavailableError("The last successful SEO data snapshot is too old");
  }
  return snapshot;
}

const inFlightSnapshots = new Map<string, Promise<unknown>>();

/**
 * One in-flight fetch per cache key for the whole process.
 *
 * unstable_cache only deduplicates revalidations within a single request, so a
 * burst of requests on the same stale key would otherwise each start their own
 * refresh. Sharing one promise also lets a blocking read join the revalidation
 * the Data Cache is already running, so the value a request returns is the same
 * value that gets stored for the requests after it.
 */
function sharedSnapshot<T>(key: string, fetchSnapshot: () => Promise<T>): Promise<T> {
  const running = inFlightSnapshots.get(key) as Promise<T> | undefined;
  if (running) return running;
  const promise = fetchSnapshot();
  inFlightSnapshots.set(key, promise);
  const settle = () => {
    if (inFlightSnapshots.get(key) === promise) inFlightSnapshots.delete(key);
  };
  // Both handlers so a rejection clears the entry without becoming an
  // unhandled rejection of its own; the callers still see the original reason.
  promise.then(settle, settle);
  return promise;
}

/**
 * Wrap one snapshot fetcher in the two caches the SEO pages depend on.
 *
 * Data Cache (`unstable_cache`) owns the last successful snapshot across
 * requests, and React `cache` keeps metadata and the page body on one snapshot
 * within a request. A failed refresh is not stored, so a recent successful
 * value keeps serving while the API recovers.
 *
 * Next.js returns an expired Data Cache entry immediately and refreshes it in
 * the background, so a value past the staleness bound has to be replaced rather
 * than rejected: the loader waits for the refresh instead of failing a request
 * the API could have answered. Joining `sharedSnapshot` means it waits for the
 * refresh the Data Cache is already running instead of starting a second one.
 */
function snapshotLoader<T extends { fetchedAt: number }>(
  cacheKeyPart: string,
  fetchSnapshot: (key: string) => Promise<T>,
) {
  const cachedSnapshot = unstable_cache(
    (key: string) => sharedSnapshot(`${cacheKeyPart}:${key}`, () => fetchSnapshot(key)),
    [cacheKeyPart],
    { revalidate: SEO_DATA_REVALIDATE_SECONDS },
  );

  return cache(async (key: string): Promise<T> => {
    const snapshot = await cachedSnapshot(key);
    if (seoSnapshotIsFresh(snapshot.fetchedAt)) return snapshot;
    // The read above left its refresh in the map, so this waits for that one.
    // Starting a fetch here instead would still be correct, only wasteful.
    return assertFresh(await sharedSnapshot(`${cacheKeyPart}:${key}`, () => fetchSnapshot(key)));
  });
}

async function fetchListingSnapshot(serializedParams: string): Promise<ListingSnapshot> {
  const params = JSON.parse(serializedParams) as SearchParams;
  const [masters, result] = await Promise.all([
    getMasters(),
    getOpportunities(params),
  ]);
  return { masters, result, fetchedAt: Date.now() };
}

/**
 * A 404 is a normal, cacheable outcome for a detail lookup. Keeping it as
 * null avoids unstable_cache retaining a rejected promise forever. Related
 * company data is deliberately best-effort and cannot make the primary page
 * unavailable.
 */
async function fetchOpportunitySnapshot(id: string): Promise<OpportunitySnapshot> {
  const itemPromise = getOpportunity(id).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  });
  const relatedPromise = getSameCompanyOpportunities(id).catch(() => {
    // The detail remains useful when the secondary recommendation query is
    // temporarily unavailable.
    return [] as Opportunity[];
  });
  const [item, sameCompanyOpportunities] = await Promise.all([itemPromise, relatedPromise]);
  if (!item) {
    return { item: null, sameCompanyOpportunities: [], fetchedAt: Date.now() };
  }
  return { item, sameCompanyOpportunities, fetchedAt: Date.now() };
}

/**
 * A company page carries its whole content in one response, so unlike the
 * opportunity detail there is no best-effort secondary fetch here: a 404 is a
 * cacheable null and every other failure propagates.
 */
async function fetchCompanySnapshot(publicCode: string): Promise<CompanySnapshot> {
  const company = await getCompany(publicCode).catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  });
  return { company, fetchedAt: Date.now() };
}

const loadListingSnapshotByKey = snapshotLoader("seo-listing-snapshot-v2", fetchListingSnapshot);
const NON_CACHEABLE_LISTING_PREFIX = "seo-listing-snapshot-direct-v1";
/**
 * The non-cacheable twin of `loadListingSnapshotByKey`: it never touches
 * `unstable_cache`, so nothing is written to disk and nothing outlives the
 * requests that are currently in flight for it. It still goes through
 * `sharedSnapshot`, because a burst of concurrent requests for the same
 * search term (several tabs, a crawler retry, or metadata and the page body
 * racing each other) should still share one database hit rather than each
 * starting their own — the only thing this path forgoes is remembering the
 * result once every caller has moved on.
 */
function loadListingSnapshotDirectly(key: string): Promise<ListingSnapshot> {
  return sharedSnapshot(`${NON_CACHEABLE_LISTING_PREFIX}:${key}`, () => fetchListingSnapshot(key));
}
const loadOpportunitySnapshotById = snapshotLoader("seo-opportunity-snapshot-v2", fetchOpportunitySnapshot);
const loadCompanySnapshotByCode = snapshotLoader("seo-company-snapshot-v1", fetchCompanySnapshot);

/**
 * Metadata and the page body call this with the same normalized key.
 *
 * A URL outside `listingSnapshotIsCacheable` bypasses the Data Cache entirely
 * rather than being written under its own key: it is already `noindex`, so
 * there is no ranking benefit to a stored snapshot, and letting a visitor mint
 * one on demand (`/?q=<random>`) is exactly the unbounded-disk-writes case this
 * guards against. Fetching directly still benefits from `getOpportunities`'
 * own retry and from `sharedSnapshot`'s in-flight dedup for a concurrent burst.
 */
export async function loadListingSnapshot(params: SearchParams): Promise<ListingSnapshot> {
  const { params: normalized, key } = normalizeListingParams(params);
  if (!listingSnapshotIsCacheable(normalized)) return loadListingSnapshotDirectly(key);
  return loadListingSnapshotByKey(key);
}

export async function loadOpportunitySnapshot(id: string): Promise<OpportunitySnapshot> {
  return loadOpportunitySnapshotById(id);
}

/** Metadata and the page body call this with the same normalized code. */
export async function loadCompanySnapshot(publicCode: string): Promise<CompanySnapshot> {
  // The API stores codes uppercase; normalizing here means a lowercase link is
  // one cache entry with the page's own redirect, not a miss on every request.
  return loadCompanySnapshotByCode(publicCode.toUpperCase());
}
