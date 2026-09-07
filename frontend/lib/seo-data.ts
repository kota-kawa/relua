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

function assertFresh<T extends { fetchedAt: number }>(snapshot: T): T {
  if (!seoSnapshotIsFresh(snapshot.fetchedAt)) {
    throw new SeoDataUnavailableError("The last successful SEO data snapshot is too old");
  }
  return snapshot;
}

/**
 * Data Cache owns the last successful complete listing snapshot. A failed
 * refresh is not stored by unstable_cache, so a recent successful value can
 * continue to serve while the API recovers. The age check stops an outage
 * from serving an unboundedly old page.
 */
const cachedListingSnapshot = unstable_cache(
  async (serializedParams: string): Promise<ListingSnapshot> => {
    const params = JSON.parse(serializedParams) as SearchParams;
    const [masters, result] = await Promise.all([
      getMasters(),
      getOpportunities(params),
    ]);
    return { masters, result, fetchedAt: Date.now() };
  },
  ["seo-listing-snapshot-v2"],
  { revalidate: SEO_DATA_REVALIDATE_SECONDS },
);

const loadListingSnapshotByKey = cache(async (key: string): Promise<ListingSnapshot> => {
  return assertFresh(await cachedListingSnapshot(key));
});

/** Metadata and the page body call this with the same normalized key. */
export async function loadListingSnapshot(params: SearchParams): Promise<ListingSnapshot> {
  return loadListingSnapshotByKey(normalizeListingParams(params).key);
}

/**
 * A 404 is a normal, cacheable outcome for a detail lookup. Keeping it as
 * null avoids unstable_cache retaining a rejected promise forever. Related
 * company data is deliberately best-effort and cannot make the primary page
 * unavailable.
 */
const cachedOpportunitySnapshot = unstable_cache(
  async (id: string): Promise<OpportunitySnapshot> => {
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
  },
  ["seo-opportunity-snapshot-v2"],
  { revalidate: SEO_DATA_REVALIDATE_SECONDS },
);

const loadOpportunitySnapshotById = cache(async (id: string): Promise<OpportunitySnapshot> => {
  return assertFresh(await cachedOpportunitySnapshot(id));
});

export async function loadOpportunitySnapshot(id: string): Promise<OpportunitySnapshot> {
  return loadOpportunitySnapshotById(id);
}

/**
 * A company page carries its whole content in one response, so unlike the
 * opportunity detail there is no best-effort secondary fetch here: a 404 is a
 * cacheable null and every other failure propagates.
 */
const cachedCompanySnapshot = unstable_cache(
  async (publicCode: string): Promise<CompanySnapshot> => {
    const company = await getCompany(publicCode).catch((error: unknown) => {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    });
    return { company, fetchedAt: Date.now() };
  },
  ["seo-company-snapshot-v1"],
  { revalidate: SEO_DATA_REVALIDATE_SECONDS },
);

const loadCompanySnapshotByCode = cache(async (publicCode: string): Promise<CompanySnapshot> => {
  return assertFresh(await cachedCompanySnapshot(publicCode));
});

/** Metadata and the page body call this with the same normalized code. */
export async function loadCompanySnapshot(publicCode: string): Promise<CompanySnapshot> {
  // The API stores codes uppercase; normalizing here means a lowercase link is
  // one cache entry with the page's own redirect, not a miss on every request.
  return loadCompanySnapshotByCode(publicCode.toUpperCase());
}
