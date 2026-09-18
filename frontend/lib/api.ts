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

async function attemptFetch<T>(path: string, timeoutMs: number): Promise<T> {
  const internalToken = process.env.API_INTERNAL_TOKEN ?? "local-development-internal-token";
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

export async function getOpportunities(params: SearchParams): Promise<OpportunityList> {
  const query = new URLSearchParams();
  const allowed = ["q", "status", "industry", "sector", "event_type", "event_format", "job_category", "graduation_year", "degree", "sort", "page"];
  allowed.forEach((key) => appendValues(query, key, params[key]));
  const rawView = Array.isArray(params.view) ? params.view[0] : params.view;
  query.set("per_page", rawView === "calendar" ? "60" : rawView === "list" ? "30" : "12");
  // The calendar groups items into months in iteration order, so it only makes
  // sense over a deadline-sorted result set.
  if (rawView === "calendar") query.set("sort", "deadline");
  return apiFetch<OpportunityList>(`/opportunities?${query.toString()}`, { retry: true });
}

/**
 * Fetch every opportunity for routes that need a complete site-wide listing.
 * These fan out one request per page, and the sitemap already answers a partial
 * failure with 503 plus Retry-After, so they are not retried here.
 */
export async function getAllOpportunities(statuses = ["status-02"]): Promise<Opportunity[]> {
  const perPage = 100;
  const common = new URLSearchParams({ per_page: String(perPage), sort: "updated" });
  statuses.forEach((status) => common.append("status", status));
  const commonQuery = common.toString();
  const firstPage = await apiFetch<OpportunityList>(`/opportunities?${commonQuery}`);
  const remainingPages = await Promise.all(
    Array.from({ length: Math.max(firstPage.total_pages - 1, 0) }, (_, index) =>
      apiFetch<OpportunityList>(`/opportunities?${commonQuery}&page=${index + 2}`),
    ),
  );

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

/**
 * Every company whose page carries its own content: a description plus at least
 * one current opening. The API decides that, so the sitemap and the pages cannot
 * disagree about which companies belong in search.
 */
export async function getAllIndexableCompanies(): Promise<CompanySummary[]> {
  const perPage = 100;
  const firstPage = await apiFetch<CompanyList>(`/companies?indexable=true&per_page=${perPage}`);
  const remainingPages = await Promise.all(
    Array.from({ length: Math.max(firstPage.total_pages - 1, 0) }, (_, index) =>
      apiFetch<CompanyList>(`/companies?indexable=true&per_page=${perPage}&page=${index + 2}`),
    ),
  );

  return [firstPage, ...remainingPages].flatMap((page) => page.items);
}
