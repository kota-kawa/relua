import type { Metadata } from "next";

import { currentGraduationYears, FILTER_KEYS, OPEN_STATUS_SLUG, valuesOf } from "@/lib/format";
import type { Masters, SearchParams } from "@/lib/types";

export const INDEXABLE_FACET_KEYS = ["industry", "event_type", "graduation_year"] as const;
export type IndexableFacetKey = typeof INDEXABLE_FACET_KEYS[number];

export type ListingFacet = {
  key: IndexableFacetKey;
  slug: string;
  label?: string;
};

export type SeoFacetCatalog = Record<IndexableFacetKey, ReadonlyMap<string, string>>;

/** Avoid creating landing pages that have too little useful listing content. */
export const MIN_INDEXABLE_CATEGORY_RESULTS = 5;

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
  facet?: ListingFacet;
};

export type ListingSeoOptions = {
  catalog?: SeoFacetCatalog;
  resultTotal?: number;
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

function usableLabel(label: string) {
  return label !== "その他" && label !== "不明";
}

/** Builds the category vocabulary that is allowed to become an SEO landing page. */
export function getSeoFacetCatalog(masters: Masters): SeoFacetCatalog {
  return {
    industry: new Map(masters.industries.filter((item) => usableLabel(item.name)).map((item) => [item.slug, item.name])),
    event_type: new Map(masters.event_types.filter((item) => usableLabel(item.name)).map((item) => [item.slug, item.name])),
    graduation_year: new Map(
      currentGraduationYears(masters.graduation_years, [])
        .filter((item) => usableLabel(item.name))
        .map((item) => [item.slug, item.name]),
    ),
  };
}

/** Returns category values that may be included in the sitemap. */
export function indexableFacetValues(masters: Masters): ListingFacet[] {
  const catalog = getSeoFacetCatalog(masters);
  return INDEXABLE_FACET_KEYS.flatMap((key) => Array.from(catalog[key], ([slug, label]) => ({ key, slug, label })));
}

function getIndexableFacet(params: SearchParams, catalog?: SeoFacetCatalog): ListingFacet | null {
  const candidates = INDEXABLE_FACET_KEYS.filter((key) => valuesOf(params, key).length > 0);
  if (candidates.length !== 1) return null;

  const key = candidates[0];
  const values = valuesOf(params, key);
  if (values.length !== 1 || !values[0]) return null;

  const label = catalog?.[key].get(values[0]);
  if (catalog && !label) return null;
  return { key, slug: values[0], label };
}

/** Builds the normalized public path for an indexable category page. */
export function listingPath(facet?: ListingFacet, page = 1) {
  const query = new URLSearchParams();
  if (facet) query.set(facet.key, facet.slug);
  if (page > 1) query.set("page", String(page));
  const serialized = query.toString();
  return serialized ? `/?${serialized}` : "/";
}

/**
 * Search-result URLs are user navigation, not all landing pages. Index the
 * default listing, pure pagination, and one high-intent category facet at a
 * time. Search, sorting, arbitrary combinations, and thin categories stay
 * out of the index while their links remain crawlable.
 */
export function getListingSeo(params: SearchParams, options: ListingSeoOptions = {}): ListingSeo {
  if (Object.keys(params).some((key) => !LISTING_QUERY_KEYS.has(key))) return noindex();
  if (valuesOf(params, "q").some(Boolean)) return noindex();
  if (valuesOf(params, "status_scope").length) return noindex();
  if (valuesOf(params, "sort").some(Boolean)) return noindex();
  if (!isDefaultStatus(params)) return noindex();

  const facet = getIndexableFacet(params, options.catalog);
  const activeFilterKeys = FILTER_KEYS.filter((key) => key !== "status" && valuesOf(params, key).some(Boolean));
  if (activeFilterKeys.length > 0 && (
    !facet
    || activeFilterKeys.length !== 1
    || activeFilterKeys[0] !== facet.key
  )) {
    return noindex();
  }

  if (facet && options.resultTotal !== undefined && options.resultTotal < MIN_INDEXABLE_CATEGORY_RESULTS) {
    return noindex();
  }

  const viewValues = valuesOf(params, "view");
  const view = first(params, "view");
  if (viewValues.length > 1 || (view && !VALID_VIEWS.has(view))) return noindex();

  const page = pageNumber(params);
  if (page === null) return noindex();
  if (page > 1 && (view === "list" || view === "calendar")) return noindex();

  return {
    index: true,
    follow: true,
    canonical: listingPath(facet ?? undefined, page),
    facet: facet ?? undefined,
  };
}

function categoryMetadata(facet: ListingFacet) {
  if (!facet.label) return null;
  const descriptionPrefix = facet.key === "graduation_year" ? "向け" : "の";
  const title = facet.key === "event_type"
    ? `${facet.label}募集情報`
    : `${facet.label}${descriptionPrefix}インターン・本選考情報`;
  const description = facet.key === "event_type"
    ? `${facet.label}の募集情報を検索できます。締切や応募条件を確認して、公式サイトから応募できます。`
    : `${facet.label}${descriptionPrefix}インターン・本選考・イベントの募集情報を検索できます。締切や応募条件を確認して、公式サイトから応募できます。`;
  return {
    title,
    description,
  };
}

export function listingMetadata(params: SearchParams, options: ListingSeoOptions = {}): Metadata {
  const seo = getListingSeo(params, options);
  const category = seo.facet ? categoryMetadata(seo.facet) : null;
  return {
    ...(category
      ? {
          title: category.title,
          description: category.description,
          openGraph: { title: category.title, description: category.description },
          twitter: { title: category.title, description: category.description },
        }
      : {}),
    alternates: seo.canonical ? { canonical: seo.canonical } : undefined,
    robots: { index: seo.index, follow: seo.follow },
  };
}
