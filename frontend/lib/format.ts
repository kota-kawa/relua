import type { MasterItem, Masters, SectorItem } from "@/lib/types";

export function formatDate(value: string | null, fallback = "日程未定") {
  if (!value) return fallback;
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "short",
    day: "numeric",
    weekday: "short",
    timeZone: "Asia/Tokyo",
  }).format(new Date(`${value}T00:00:00+09:00`));
}

/**
 * Formats a timezone-aware instant as the calendar day it falls on in Tokyo.
 *
 * `formatDate` takes a date-only string, so callers used to slice the first ten
 * characters off an ISO instant. The API serialises `DateTime(timezone=True)`
 * columns with a UTC offset, so that slice yields the UTC day: anything checked
 * between 00:00 and 09:00 JST rendered as the previous day.
 */
export function formatInstantDate(value: string | null, fallback = "日程未定") {
  if (!value) return fallback;
  const instant = new Date(value);
  if (Number.isNaN(instant.getTime())) return fallback;
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "short",
    day: "numeric",
    weekday: "short",
    timeZone: "Asia/Tokyo",
  }).format(instant);
}

const DAY_IN_MS = 86_400_000;
const tokyoDateParts = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "numeric",
  day: "numeric",
  timeZone: "Asia/Tokyo",
});

/** Converts an instant into the matching calendar day in Tokyo. */
function tokyoDay(timestamp: number) {
  const parts = tokyoDateParts.formatToParts(new Date(timestamp));
  const valueOf = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((part) => part.type === type)?.value);
  return Date.UTC(valueOf("year"), valueOf("month") - 1, valueOf("day"));
}

export function daysUntil(value: string | null) {
  if (!value) return null;
  const deadlineDay = new Date(`${value}T00:00:00Z`).getTime();
  return (deadlineDay - tokyoDay(Date.now())) / DAY_IN_MS;
}

export function deadlineLabel(value: string | null) {
  const days = daysUntil(value);
  if (days === null) return "締切未定";
  if (days < 0) return "受付終了";
  if (days === 0) return "本日締切";
  if (days === 1) return "明日締切";
  if (days <= 7) return `あと${days}日`;
  return formatDate(value);
}

/**
 * True when deadlineLabel returns a relative phrase ("あと3日") rather than the
 * date itself — i.e. when it still makes sense to show the date alongside it.
 */
export function deadlineIsRelative(value: string | null) {
  const days = daysUntil(value);
  return days !== null && days <= 7;
}

/**
 * Card variant: the card has no column header, so a distant deadline would
 * otherwise render as a bare date with nothing saying what it is.
 */
export function deadlineChipLabel(value: string | null) {
  if (deadlineIsRelative(value) || value === null) return deadlineLabel(value);
  return `締切 ${formatDate(value, "")}`;
}

/**
 * Sticky-bar variant: the bar shares one line with the entry button, so a
 * distant deadline is shortened to "8月7日(金)" instead of the full date.
 */
export function deadlineCompactLabel(value: string | null) {
  if (deadlineIsRelative(value) || value === null) return deadlineLabel(value);
  return new Intl.DateTimeFormat("ja-JP", {
    month: "short",
    day: "numeric",
    weekday: "short",
    timeZone: "Asia/Tokyo",
  }).format(new Date(`${value}T00:00:00+09:00`));
}

export function selected(params: Record<string, string | string[] | undefined>, key: string, value: string) {
  const current = params[key];
  return Array.isArray(current) ? current.includes(value) : current === value;
}

/** Paging links. Deliberately free of the `#listings` anchor: a hash stays in
 *  the URL for the life of the entry, so the browser would replay it instead of
 *  the reader's own position every time they came back to this page. Pagination
 *  scrolls to the results itself — see components/pagination.tsx. */
export function withQuery(
  params: Record<string, string | string[] | undefined>,
  changes: Record<string, string | undefined>,
  basePath = "/",
) {
  const next = new URLSearchParams();
  const omitDefaultStatus = hasDefaultOpenStatus(params);
  Object.entries(params).forEach(([key, value]) => {
    if (omitDefaultStatus && key === "status") return;
    if (Array.isArray(value)) value.forEach((entry) => next.append(key, entry));
    else if (value) next.set(key, value);
  });
  Object.entries(changes).forEach(([key, value]) => {
    if (value) next.set(key, value);
    else next.delete(key);
  });
  return `${basePath}?${next.toString()}`;
}

/** Builds a listing URL from the current filter form and always resets pagination. */
export function filterHref(entries: Iterable<[string, string]>, includeListingAnchor = true) {
  const source = Array.from(entries);
  const statusValues = source.filter(([key]) => key === "status").map(([, value]) => value);
  const omitDefaultStatus = statusValues.length === 1 && statusValues[0] === OPEN_STATUS_SLUG;
  const next = new URLSearchParams();
  for (const [key, value] of source) {
    if (key === "page" || !value || (omitDefaultStatus && key === "status")) continue;
    next.append(key, value);
  }
  const query = next.toString();
  const anchor = includeListingAnchor ? "#listings" : "";
  return query ? `/?${query}${anchor}` : `/${anchor}`;
}

/** Every query key that narrows the result set, in the order chips are shown. */
export const FILTER_KEYS = [
  "status",
  "graduation_year",
  "event_type",
  "industry",
  "sector",
  "job_category",
  "degree",
  "event_format",
] as const;

/** The listing is useful by default only when it shows opportunities people
 * can apply to now. `status_scope=all` is the explicit opt-out used when the
 * user unchecks that baseline. It is intentionally a UI-only parameter, so
 * the API continues to receive only real status values. */
export const OPEN_STATUS_SLUG = "status-02";
export const ALL_STATUS_SCOPE = "all";

export function withDefaultOpenStatus(params: Record<string, string | string[] | undefined>) {
  if (valuesOf(params, "status").length || valuesOf(params, "status_scope").includes(ALL_STATUS_SCOPE)) return params;
  return { ...params, status: OPEN_STATUS_SLUG };
}

export function valuesOf(params: Record<string, string | string[] | undefined>, key: string) {
  const value = params[key];
  return Array.isArray(value) ? value : value ? [value] : [];
}

/** The normal listing baseline is not a user-applied filter, so it should not
 * add an active-filter chip or badge to the simplified interface. */
export function hasDefaultOpenStatus(params: Record<string, string | string[] | undefined>) {
  const statuses = valuesOf(params, "status");
  return statuses.length === 1
    && statuses[0] === OPEN_STATUS_SLUG
    && !valuesOf(params, "status_scope").includes(ALL_STATUS_SCOPE);
}

/** Values suitable for public links. The default open-status scope is applied
 * server-side, so keeping its synthetic query parameter only creates duplicate
 * listing URLs. Explicit multi-status selections remain intact. */
export function publicValuesOf(params: Record<string, string | string[] | undefined>, key: string) {
  if (key === "status" && hasDefaultOpenStatus(params)) return [];
  return valuesOf(params, key);
}

export function activeFilterCount(params: Record<string, string | string[] | undefined>) {
  const total = FILTER_KEYS.reduce((count, key) => count + valuesOf(params, key).length, 0);
  return total - (hasDefaultOpenStatus(params) ? 1 : 0);
}

/** Same params plus one filter value — used by the quick filter chips. */
export function withFilter(
  params: Record<string, string | string[] | undefined>,
  key: string,
  value: string,
) {
  const next = new URLSearchParams();
  const omitDefaultStatus = hasDefaultOpenStatus(params);
  Object.entries(params).forEach(([entryKey, entryValue]) => {
    if (entryKey === "page") return;
    if (omitDefaultStatus && entryKey === "status") return;
    const list = Array.isArray(entryValue) ? entryValue : entryValue ? [entryValue] : [];
    list.forEach((entry) => next.append(entryKey, entry));
  });
  next.append(key, value);
  return `/?${next.toString()}#listings`;
}

/** Same params minus one filter value — used by the chips' remove links. */
export function withoutFilter(
  params: Record<string, string | string[] | undefined>,
  key: string,
  value: string,
) {
  const next = new URLSearchParams();
  const omitDefaultStatus = hasDefaultOpenStatus(params);
  Object.entries(params).forEach(([entryKey, entryValue]) => {
    if (entryKey === "page") return;
    if (omitDefaultStatus && entryKey === "status") return;
    const list = Array.isArray(entryValue) ? entryValue : entryValue ? [entryValue] : [];
    list.forEach((entry) => {
      if (entryKey === key && entry === value) return;
      next.append(entryKey, entry);
    });
  });
  const query = next.toString();
  return query ? `/?${query}#listings` : "/#listings";
}

/** Drops every filter but keeps the things that are not filters (query, view, sort). */
export function withoutAllFilters(params: Record<string, string | string[] | undefined>) {
  const next = new URLSearchParams();
  (["q", "view", "sort"] as const).forEach((key) => {
    valuesOf(params, key).forEach((entry) => next.append(key, entry));
  });
  const query = next.toString();
  return query ? `/?${query}#listings` : "/#listings";
}

/**
 * Every industry carries its own "その他" sector, so the flat 業種 filter list
 * renders 14 checkboxes all labelled "その他" with nothing to tell them apart.
 * Qualify only the ambiguous names with their parent industry; sector names
 * that are already unique are returned untouched.
 *
 * Display only — the checkbox value stays the slug, so the submitted filter is
 * unchanged.
 */
export function labelledSectors(masters: Masters): SectorItem[] {
  const occurrences = new Map<string, number>();
  masters.sectors.forEach((sector) => {
    occurrences.set(sector.name, (occurrences.get(sector.name) ?? 0) + 1);
  });
  const industryName = new Map(masters.industries.map((industry) => [industry.id, industry.name]));
  return masters.sectors.map((sector) => {
    const parent = industryName.get(sector.industry_id);
    if ((occurrences.get(sector.name) ?? 0) < 2 || !parent) return sector;
    return { ...sector, name: `${sector.name}（${parent}）` };
  });
}

/** "不明" is a data-quality state, not something anyone sets out to search for
 *  ("募集状況が不明な募集だけ見たい" is not a goal). Hiding it from the filter
 *  does not hide those listings: with no status selected, every status shows.
 *  Slug per backend/app/master_data.py (status-01..05). */
const UNSEARCHABLE_STATUS = "status-05";

/**
 * Drops filter options nobody can act on, while keeping any option the current
 * URL already selects so it stays visible and can be unchecked.
 */
export function searchableStatuses(items: MasterItem[], selected: string[]): MasterItem[] {
  return items.filter((item) => item.slug !== UNSEARCHABLE_STATUS || selected.includes(item.slug));
}

/** "その他" and "不明" describe a data bucket rather than an intent to search.
 * Preserve an already-selected value so older shared URLs remain reversible. */
export function actionableFilterItems(items: MasterItem[], selected: string[]): MasterItem[] {
  return items.filter((item) => selected.includes(item.slug) || (item.name !== "その他" && item.name !== "不明"));
}

/**
 * Graduation cohorts whose March has already passed are dead options — 26卒 is
 * not job-hunting in July 2026. Derived from the label rather than hardcoded so
 * the list stays correct on its own as the master gains 31卒, 32卒…
 *
 * The year is read in Asia/Tokyo on both server and client so SSR and hydration
 * agree regardless of where either runs. The backend master can add future cohorts
 * without requiring this filter to change. Labels that are not a cohort
 * ("学年不問") are always kept, as is anything the URL already selects.
 */
export function currentGraduationYears(items: MasterItem[], selected: string[], now = new Date()): MasterItem[] {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "numeric",
  }).formatToParts(now);
  const year = Number(parts.find((part) => part.type === "year")?.value);
  const month = Number(parts.find((part) => part.type === "month")?.value);
  /* Japanese academic years end in March, so a cohort is spent once April of
     its graduation year has begun. */
  const oldestLive = month >= 4 ? year + 1 : year;
  return items.filter((item) => {
    if (selected.includes(item.slug)) return true;
    const cohort = /^(\d{2})卒$/.exec(item.name);
    return !cohort || 2000 + Number(cohort[1]) >= oldestLive;
  });
}
