import "server-only";

import type { Masters, Opportunity, OpportunityList, SearchParams } from "@/lib/types";

const baseUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function apiFetch<T>(path: string): Promise<T> {
  const internalToken = process.env.API_INTERNAL_TOKEN ?? "local-development-internal-token";
  const response = await fetch(`${baseUrl}/api/v1${path}`, {
    next: { revalidate: 60 },
    headers: { Accept: "application/json", "X-Internal-API-Token": internalToken },
  });
  if (!response.ok) {
    throw new ApiError(response.status, `API request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
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
  return apiFetch<OpportunityList>(`/opportunities?${query.toString()}`);
}

/** Fetch every opportunity for routes that need a complete site-wide listing. */
export async function getAllOpportunities(): Promise<Opportunity[]> {
  const perPage = 100;
  const firstPage = await apiFetch<OpportunityList>(`/opportunities?per_page=${perPage}&sort=updated`);
  const remainingPages = await Promise.all(
    Array.from({ length: firstPage.total_pages - 1 }, (_, index) =>
      apiFetch<OpportunityList>(`/opportunities?per_page=${perPage}&sort=updated&page=${index + 2}`),
    ),
  );

  return [firstPage, ...remainingPages].flatMap((page) => page.items);
}

export async function getOpportunity(id: string): Promise<Opportunity> {
  return apiFetch<Opportunity>(`/opportunities/${encodeURIComponent(id)}`);
}

export async function getSameCompanyOpportunities(id: string): Promise<Opportunity[]> {
  return apiFetch<Opportunity[]>(`/opportunities/${encodeURIComponent(id)}/same-company`);
}

export async function getMasters(): Promise<Masters> {
  return apiFetch<Masters>("/masters");
}
