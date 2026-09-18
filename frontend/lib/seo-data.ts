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
import type { CompanyDetail, Masters, Opportunity, OpportunityList, SearchParams } from "@/lib/types";

export const SEO_DATA_REVALIDATE_SECONDS = 60;
export const SEO_DATA_MAX_STALE_MS = 60 * 60 * 1000;

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
const loadOpportunitySnapshotById = snapshotLoader("seo-opportunity-snapshot-v2", fetchOpportunitySnapshot);
const loadCompanySnapshotByCode = snapshotLoader("seo-company-snapshot-v1", fetchCompanySnapshot);

/** Metadata and the page body call this with the same normalized key. */
export async function loadListingSnapshot(params: SearchParams): Promise<ListingSnapshot> {
  return loadListingSnapshotByKey(normalizeListingParams(params).key);
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
