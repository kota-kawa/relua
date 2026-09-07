import type { Metadata } from "next";

import { currentGraduationYears, daysUntil, FILTER_KEYS, OPEN_STATUS_SLUG, valuesOf } from "@/lib/format";
import { opportunityPath } from "@/lib/site";
import type { Masters, Opportunity, SearchParams } from "@/lib/types";

export const INDEXABLE_FACET_KEYS = [
  "industry",
  "sector",
  "job_category",
  "event_type",
  "event_format",
  "graduation_year",
] as const;
export type IndexableFacetKey = typeof INDEXABLE_FACET_KEYS[number];

export type ListingFacet = {
  key: IndexableFacetKey;
  slug: string;
  label?: string;
};

export type SeoFacetCatalog = Record<IndexableFacetKey, ReadonlyMap<string, string>>;

/**
 * SEO category membership is deliberately a reviewed, typed configuration.
 *
 * The API master is still the source of labels and parent relationships, but
 * inventory changes cannot silently add or remove crawlable landing pages.
 * Add a new value here after reviewing its intent and content quality. Past
 * graduation cohorts are filtered separately by currentGraduationYears().
 */
export const SEO_FACET_ALLOWLIST: Readonly<Record<IndexableFacetKey, readonly string[]>> = {
  industry: [
    "industry-01", "industry-02", "industry-03", "industry-04", "industry-05",
    "industry-06", "industry-07", "industry-08", "industry-09", "industry-10",
    "industry-11", "industry-12", "industry-13", "industry-14",
  ],
  sector: [
    "sector-1-01", "sector-1-02", "sector-1-03", "sector-1-04", "sector-1-05", "sector-1-71",
    "sector-2-07", "sector-2-08", "sector-2-09", "sector-2-10", "sector-2-11", "sector-2-12", "sector-2-13",
    "sector-3-16",
    "sector-4-18", "sector-4-19", "sector-4-20", "sector-4-21", "sector-4-22",
    "sector-5-24", "sector-5-25", "sector-5-26", "sector-5-27",
    "sector-6-29", "sector-6-30", "sector-6-31", "sector-6-32",
    "sector-7-34", "sector-7-35", "sector-7-36", "sector-7-37",
    "sector-8-39", "sector-8-41", "sector-8-42",
    "sector-9-44", "sector-9-45", "sector-9-46",
    "sector-10-48", "sector-10-49", "sector-10-50",
    "sector-11-54", "sector-11-55", "sector-11-56",
    "sector-12-58", "sector-12-59", "sector-12-60", "sector-12-61",
    "sector-13-64",
    "sector-14-66", "sector-14-68",
  ],
  job_category: [
    "job-01", "job-02", "job-03", "job-04", "job-05", "job-06",
    "job-07", "job-08", "job-09", "job-10", "job-11", "job-12",
    "job-13", "job-14", "job-15", "job-16", "job-17", "job-18",
  ],
  event_type: ["type-01", "type-02", "type-03", "type-04", "type-05"],
  event_format: ["format-01", "format-02", "format-03"],
  graduation_year: ["grad-02", "grad-03", "grad-04", "grad-05", "grad-06"],
};

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
  totalPages?: number;
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
  const catalogFor = <T extends { slug: string; name: string }>(key: IndexableFacetKey, items: T[]) => {
    const allowed = new Set(SEO_FACET_ALLOWLIST[key]);
    return new Map(items
      .filter((item) => allowed.has(item.slug) && usableLabel(item.name))
      .map((item) => [item.slug, item.name] as const));
  };

  return {
    industry: catalogFor("industry", masters.industries),
    sector: catalogFor("sector", masters.sectors),
    job_category: catalogFor("job_category", masters.job_categories),
    event_type: catalogFor("event_type", masters.event_types),
    event_format: catalogFor("event_format", masters.event_formats),
    graduation_year: new Map(
      currentGraduationYears(masters.graduation_years, [])
        .filter((item) => SEO_FACET_ALLOWLIST.graduation_year.includes(item.slug) && usableLabel(item.name))
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

  if (!SEO_FACET_ALLOWLIST[key].includes(values[0])) return null;
  const label = catalog?.[key]?.get(values[0]);
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
 * default listing, pure pagination, and one reviewed high-intent category
 * facet at a time. Search, sorting, and arbitrary combinations stay out of
 * the index while their links remain crawlable. Availability (including a
 * normal zero-result category) is handled by the page loader so the route can
 * return a real 404 instead of a robots directive.
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

  const viewValues = valuesOf(params, "view");
  const view = first(params, "view");
  if (viewValues.length > 1 || (view && !VALID_VIEWS.has(view))) return noindex();

  const page = pageNumber(params);
  if (page === null) return noindex();
  if (options.totalPages !== undefined && page > Math.max(options.totalPages, 1)) return noindex();
  if (page > 1 && (view === "list" || view === "calendar")) return noindex();

  return {
    index: true,
    follow: true,
    canonical: listingPath(facet ?? undefined, page),
    facet: facet ?? undefined,
  };
}

function categoryMetadata(facet: ListingFacet, page: number) {
  if (!facet.label) return null;
  const subject = facet.key === "graduation_year"
    ? `${facet.label}向け`
    : facet.key === "event_format"
      ? `${facet.label}で参加できる`
      : `${facet.label}の`;
  const baseTitle = facet.key === "event_type"
    ? `${facet.label}の募集情報`
    : `${subject}インターン・新卒採用情報`;
  const title = page > 1 ? `${baseTitle}（${page}ページ目）` : baseTitle;
  const description = facet.key === "event_type"
    ? `${facet.label}の募集情報を比較できます。応募締切、対象学年、開催形式を確認し、企業の公式サイトから応募できます。${page > 1 ? `${page}ページ目です。` : ""}`
    : `${subject}インターン・本選考・イベントを比較できます。応募締切、対象学年、開催形式を確認し、企業の公式サイトから応募できます。${page > 1 ? `${page}ページ目です。` : ""}`;
  return {
    title,
    description,
  };
}

export function listingMetadata(params: SearchParams, options: ListingSeoOptions = {}): Metadata {
  const seo = getListingSeo(params, options);
  const page = pageNumber(params) ?? 1;
  const category = seo.facet ? categoryMetadata(seo.facet, page) : null;
  const listingPage = !category && seo.index && page > 1
    ? {
        title: `インターン・本選考 募集一覧（${page}ページ目）`,
        description: `現在応募できるインターン・本選考・イベントの募集一覧、${page}ページ目です。締切や応募条件を比較できます。`,
      }
    : null;
  const appearance = category ?? listingPage;
  return {
    ...(appearance
      ? {
          title: { absolute: `${appearance.title} | relua` },
          description: appearance.description,
          openGraph: { title: appearance.title, description: appearance.description, url: seo.canonical },
          twitter: { title: appearance.title, description: appearance.description },
        }
      : {}),
    alternates: seo.canonical ? { canonical: seo.canonical } : undefined,
    robots: {
      index: seo.index,
      follow: seo.follow,
      googleBot: {
        index: seo.index,
        follow: seo.follow,
        "max-image-preview": "large",
        "max-snippet": -1,
        "max-video-preview": -1,
      },
    },
  };
}

const INDEXABLE_OPPORTUNITY_STATUS_SLUGS = new Set(["status-01", "status-02", "status-04"]);

export function opportunityIsIndexable(item: Opportunity) {
  const remaining = daysUntil(item.deadline);
  return INDEXABLE_OPPORTUNITY_STATUS_SLUGS.has(item.recruitment_status.slug)
    && (remaining === null || remaining >= 0);
}

export function opportunityMetadata(item: Opportunity): Metadata {
  const path = opportunityPath(item.public_code);
  const index = opportunityIsIndexable(item);
  const audience = item.graduation_years.map((value) => value.name).join("・");
  const deadline = item.deadline ? `応募締切は${item.deadline}。` : "応募締切は企業の公式情報をご確認ください。";
  const summary = item.description.replace(/\s+/g, " ").trim();
  const description = `${summary.slice(0, 105)}${summary.length > 105 ? "…" : ""} ${audience ? `${audience}対象。` : ""}${deadline}`.slice(0, 160);
  const title = `${item.company.name} ${item.event_name}`;

  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: {
      title,
      description,
      url: path,
      type: "website",
    },
    twitter: { title, description },
    robots: {
      index,
      follow: true,
      googleBot: {
        index,
        follow: true,
        "max-image-preview": "large",
        "max-snippet": -1,
        "max-video-preview": -1,
      },
    },
  };
}
