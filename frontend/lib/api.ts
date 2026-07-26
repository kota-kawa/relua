import type { Masters, Opportunity, OpportunityList, SearchParams } from "@/lib/types";

const baseUrl = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function apiFetch<T>(path: string): Promise<T> {
  const response = await fetch(`${baseUrl}/api/v1${path}`, {
    next: { revalidate: 60 },
    headers: { Accept: "application/json" },
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
  const allowed = ["q", "status", "industry", "sector", "event_type", "event_format", "job_category", "graduation_year", "sort", "page"];
  allowed.forEach((key) => appendValues(query, key, params[key]));
  const rawView = Array.isArray(params.view) ? params.view[0] : params.view;
  query.set("per_page", rawView === "calendar" ? "60" : rawView === "list" ? "30" : "12");
  return apiFetch<OpportunityList>(`/opportunities?${query.toString()}`);
}

export async function getOpportunity(id: string): Promise<Opportunity> {
  return apiFetch<Opportunity>(`/opportunities/${encodeURIComponent(id)}`);
}

export async function getMasters(): Promise<Masters> {
  return apiFetch<Masters>("/masters");
}
