import type { Metadata } from "next";

import { FILTER_KEYS, OPEN_STATUS_SLUG, valuesOf } from "@/lib/format";
import type { SearchParams } from "@/lib/types";

const LISTING_QUERY_KEYS = new Set([
  "q",
  "status",
  "status_scope",
  "sort",
  "page",
  "view",
  ...FILTER_KEYS,
]);

const VALID_VIEWS = new Set(["cards", "list", "calendar"]);

export type ListingSeo = {
  index: boolean;
  follow: true;
  canonical?: string;
};

function noindex(): ListingSeo {
  return { index: false, follow: true };
}

function first(params: SearchParams, key: string) {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}

function isDefaultStatus(params: SearchParams) {
  const statuses = valuesOf(params, "status");
  return statuses.length === 0 || (
    statuses.length === 1
    && statuses[0] === OPEN_STATUS_SLUG
    && !valuesOf(params, "status_scope").includes("all")
  );
}

function pageNumber(params: SearchParams) {
  const values = valuesOf(params, "page");
  if (values.length === 0) return 1;
  if (values.length !== 1 || !/^\d+$/.test(values[0])) return null;
  const page = Number(values[0]);
  return Number.isSafeInteger(page) && page >= 1 ? page : null;
}

/**
 * Search-result URLs are user navigation, not landing pages. Keep only the
 * unfiltered default listing and its pure card-view pagination indexable.
 * Presentation-only view variants can consolidate on page one, while their
 * later pages are noindex because list/calendar use different page sizes.
 */
export function getListingSeo(params: SearchParams): ListingSeo {
  if (Object.keys(params).some((key) => !LISTING_QUERY_KEYS.has(key))) return noindex();
  if (valuesOf(params, "q").some(Boolean)) return noindex();
  if (valuesOf(params, "status_scope").length) return noindex();
  if (valuesOf(params, "sort").some(Boolean)) return noindex();
  if (!isDefaultStatus(params)) return noindex();
  if (FILTER_KEYS.some((key) => key !== "status" && valuesOf(params, key).some(Boolean))) return noindex();

  const viewValues = valuesOf(params, "view");
  const view = first(params, "view");
  if (viewValues.length > 1 || (view && !VALID_VIEWS.has(view))) return noindex();

  const page = pageNumber(params);
  if (page === null) return noindex();
  if (page > 1 && (view === "list" || view === "calendar")) return noindex();

  return {
    index: true,
    follow: true,
    canonical: page > 1 ? `/?page=${page}` : "/",
  };
}

export function listingMetadata(params: SearchParams): Metadata {
  const seo = getListingSeo(params);
  return {
    alternates: seo.canonical ? { canonical: seo.canonical } : undefined,
    robots: { index: seo.index, follow: seo.follow },
  };
}
