import "server-only";

import type { CompanyDetail, CompanyList, CompanySummary, Masters, Opportunity, OpportunityList, SearchParams } from "@/lib/types";

const baseUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
const configuredTimeout = Number(process.env.API_INTERNAL_TIMEOUT_MS ?? "10000");
const API_TIMEOUT_MS = Number.isFinite(configuredTimeout) && configuredTimeout > 0 ? configuredTimeout : 10000;
/**
 * A page that has to wait for fresh data cannot fall back to a stored snapshot,
 * so one connection reset or one 502 from a restarting API would otherwise be a
 * 5xx for that visitor. One extra attempt covers that without turning a real
 * outage into a queue: `API_TIMEOUT_MS` is the budget for the whole call, so a
 * slow attempt leaves no room for a retry and only a cheap failure is repeated.
 * Callers that fan out over every page, and callers that already have their own
 * degraded answer, opt out so an outage is not amplified where it buys nothing.
 */
const API_RETRY_ATTEMPTS = 2;
const API_RETRY_BACKOFF_MS = 100;
/** Spread simultaneous failures so N parallel reads do not retry in one burst. */
const API_RETRY_JITTER_MS = 100;
/** Enough time left for a retry to plausibly finish rather than just delay the error. */
const API_RETRY_MIN_REMAINING_MS = 200;
/**
 * The sitemap walks every page of two collections, so a single unauthenticated
 * request would otherwise open one internal connection per page all at once.
 * The pages are still fetched concurrently, just in bounded groups, the same
 * shape `lib/browser-api.ts` uses for its own fan-out.
 */
const FAN_OUT_CONCURRENCY = 6;
/** Mirrors the internal API's own `max_length=100` on `q`. */
const MAX_QUERY_CHARACTERS = 100;
/** The orderings the internal API accepts; it answers anything else with 422. */
const SORT_VALUES = new Set(["relevance", "deadline", "updated", "created"]);
const DEVELOPMENT_INTERNAL_TOKEN = "local-development-internal-token";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/**
 * 5xx is the API failing to answer a question it accepted; 4xx is the answer.
 * `fetch` reports a transport failure as a TypeError, which also keeps an
 * AbortError from our own timeout (it has spent the budget) and a SyntaxError
 * from a non-JSON body (repeating it would return the same body) out.
 */
function isRetryable(error: unknown) {
  if (error instanceof ApiError) return error.status >= 500;
  return error instanceof TypeError;
}

/**
 * The published development token is a convenience for `docker compose up`, not
 * a credential, so a production process that would send it has no token at all
 * and must say so rather than authenticate itself with a value anyone can read
 * out of this repository. `proxy.ts` keeps its own copy of this rule because it
 * runs in the middleware bundle and cannot import a `server-only` module.
 */
function internalApiToken() {
  const token = process.env.API_INTERNAL_TOKEN;
  if (token) return token;
  if (process.env.NODE_ENV === "production") {
    throw new Error("API_INTERNAL_TOKEN must be set: the development default is not a credential");
  }
  return DEVELOPMENT_INTERNAL_TOKEN;
}

async function attemptFetch<T>(path: string, timeoutMs: number): Promise<T> {
  const internalToken = internalApiToken();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${baseUrl}/api/v1${path}`, {
      cache: "no-store",
      signal: controller.signal,
      headers: { Accept: "application/json", "X-Internal-API-Token": internalToken },
    });
    if (!response.ok) {
      // Release the connection rather than leaving the body for the collector,
      // which matters most when the API is failing and the call is repeated.
      await response.body?.cancel().catch(() => undefined);
      throw new ApiError(response.status, `API request failed: ${response.status}`);
    }
    return await response.json() as T;
  } finally {
    clearTimeout(timeout);
  }
}

async function apiFetch<T>(path: string, { retry = false } = {}): Promise<T> {
  const deadline = Date.now() + API_TIMEOUT_MS;
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await attemptFetch<T>(path, deadline - Date.now());
    } catch (error) {
      if (!retry || attempt >= API_RETRY_ATTEMPTS || !isRetryable(error)) throw error;
      const backoff = API_RETRY_BACKOFF_MS + Math.random() * API_RETRY_JITTER_MS;
      if (deadline - Date.now() - backoff < API_RETRY_MIN_REMAINING_MS) throw error;
      await new Promise((resolve) => setTimeout(resolve, backoff));
      // The wait can overrun on a busy event loop. Retrying with no budget left
      // would only replace the real error with a timeout.
      if (deadline - Date.now() < API_RETRY_MIN_REMAINING_MS) throw error;
    }
  }
}

function appendValues(target: URLSearchParams, key: string, value: string | string[] | undefined) {
  if (Array.isArray(value)) value.forEach((item) => item && target.append(key, item));
  else if (value) target.set(key, value);
}

function firstValue(value: string | string[] | undefined) {
  return Array.isArray(value) ? value.find(Boolean) : value;
}

/**
 * Repair the three listing parameters the internal API constrains.
 *
 * `q`, `sort` and `page` are the only ones it validates, and it answers a value
 * it cannot accept with 422 — which is not retryable and has no caller that can
 * do anything with it, so `/?sort=new`, `/?page=0` or a 101-character search
 * would reach the visitor as a 5xx. The rule is to fall back to the API's own
 * default rather than to guess: an unusable value is dropped, so the request
 * still describes a page that exists. Dropping rather than clamping also keeps
 * `lib/seo.ts` consistent, which independently marks an unparsable or
 * out-of-range page `noindex`; a page number that is merely past the end is
 * forwarded untouched so the route can still answer it with a real 404.
 *
 * The filter values are left alone: the API takes them as free-form lists and
 * an unknown slug is an empty result, not an error.
 */
export function listingApiParams(params: SearchParams): { q?: string; sort?: string; page?: string } {
  const rawQuery = firstValue(params.q);
  // Pydantic counts code points, so the cut is made over code points too and a
  // surrogate pair is never split in half on the way out.
  const characters = rawQuery ? Array.from(rawQuery) : [];
  const q = characters.length > MAX_QUERY_CHARACTERS
    ? characters.slice(0, MAX_QUERY_CHARACTERS).join("")
    : rawQuery || undefined;

  const rawSort = firstValue(params.sort);
  const sort = rawSort && SORT_VALUES.has(rawSort) ? rawSort : undefined;

  const rawPage = firstValue(params.page);
  // `\d+` alone, so "+1", " 1", "1.0" and "1e3" are rejected rather than coerced
  // into a page the visitor did not ask for.
  const pageNumber = rawPage && /^\d+$/.test(rawPage) ? Number(rawPage) : Number.NaN;
  const page = Number.isSafeInteger(pageNumber) && pageNumber >= 1 ? String(pageNumber) : undefined;

  return { q, sort, page };
}

export async function getOpportunities(params: SearchParams): Promise<OpportunityList> {
  const query = new URLSearchParams();
  const allowed = ["status", "industry", "sector", "event_type", "event_format", "job_category", "graduation_year", "degree"];
  allowed.forEach((key) => appendValues(query, key, params[key]));
  const validated = listingApiParams(params);
  if (validated.q) query.set("q", validated.q);
  if (validated.sort) query.set("sort", validated.sort);
  if (validated.page) query.set("page", validated.page);
  const rawView = Array.isArray(params.view) ? params.view[0] : params.view;
  query.set("per_page", rawView === "calendar" ? "60" : rawView === "list" ? "30" : "12");
  // The calendar groups items into months in iteration order, so it only makes
  // sense over a deadline-sorted result set.
  if (rawView === "calendar") query.set("sort", "deadline");
  return apiFetch<OpportunityList>(`/opportunities?${query.toString()}`, { retry: true });
}

/**
 * Read pages 2..n in bounded groups rather than in one burst. `Promise.all` over
 * every page turns one request for a complete collection into as many
 * simultaneous internal requests as the collection has pages, which is a fan-out
 * an anonymous visitor could repeat at will.
 */
async function fetchRemainingPages<T>(totalPages: number, fetchPage: (page: number) => Promise<T>): Promise<T[]> {
  const pages = Array.from({ length: Math.max(totalPages - 1, 0) }, (_, index) => index + 2);
  const results: T[] = [];
  for (let offset = 0; offset < pages.length; offset += FAN_OUT_CONCURRENCY) {
    results.push(...await Promise.all(pages.slice(offset, offset + FAN_OUT_CONCURRENCY).map(fetchPage)));
  }
  return results;
}

/**
 * Fetch every opportunity for routes that need a complete site-wide listing.
 * These fan out one request per page, and the sitemap already answers a partial
 * failure with 503 plus Retry-After, so they are not retried here.
 *
 * The ordering has to be one that does not move while the walk is in progress:
 * `updated` is rewritten by every edit and by the source-check job, so a row
 * touched between page 1 and page 7 moves to the front and is read twice while
 * another row is pushed past the boundary and never read at all. `created_at`
 * is written once and the API breaks its ties on the row id, so only a genuinely
 * new posting can shift the window, and only by the number of rows added during
 * the walk.
 */
export async function getAllOpportunities(statuses = ["status-02"]): Promise<Opportunity[]> {
  const perPage = 100;
  const common = new URLSearchParams({ per_page: String(perPage), sort: "created" });
  statuses.forEach((status) => common.append("status", status));
  const commonQuery = common.toString();
  const firstPage = await apiFetch<OpportunityList>(`/opportunities?${commonQuery}`);
  const remainingPages = await fetchRemainingPages(firstPage.total_pages, (page) =>
    apiFetch<OpportunityList>(`/opportunities?${commonQuery}&page=${page}`));

  return [firstPage, ...remainingPages].flatMap((page) => page.items);
}

export async function getOpportunity(id: string): Promise<Opportunity> {
  return apiFetch<Opportunity>(`/opportunities/${encodeURIComponent(id)}`, { retry: true });
}

export async function getSameCompanyOpportunities(id: string): Promise<Opportunity[]> {
  return apiFetch<Opportunity[]>(`/opportunities/${encodeURIComponent(id)}/same-company`, { retry: true });
}

export async function getMasters(): Promise<Masters> {
  return apiFetch<Masters>("/masters", { retry: true });
}

export async function getCompany(publicCode: string): Promise<CompanyDetail> {
  return apiFetch<CompanyDetail>(`/companies/${encodeURIComponent(publicCode)}`, { retry: true });
}

/** One page of the companies whose profile makes them indexable, ordered by name. */
export async function getCompanies(page: number, perPage: number): Promise<CompanyList> {
  return apiFetch<CompanyList>(`/companies?indexable=true&per_page=${perPage}&page=${page}`, { retry: true });
}

/**
 * Every company whose page carries its own content: a written profile. The API
 * decides that, so the sitemap and the pages cannot disagree about which
 * companies belong in search.
 */
export async function getAllIndexableCompanies(): Promise<CompanySummary[]> {
  const perPage = 100;
  // The API orders this listing by name then id, which is stable for the length
  // of the walk, so unlike the opportunity fan-out there is nothing to ask for
  // here. The pages are still read in bounded groups for the same reason.
  const firstPage = await apiFetch<CompanyList>(`/companies?indexable=true&per_page=${perPage}`);
  const remainingPages = await fetchRemainingPages(firstPage.total_pages, (page) =>
    apiFetch<CompanyList>(`/companies?indexable=true&per_page=${perPage}&page=${page}`));

  return [firstPage, ...remainingPages].flatMap((page) => page.items);
}
