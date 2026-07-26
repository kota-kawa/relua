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

export function daysUntil(value: string | null) {
  if (!value) return null;
  const deadline = new Date(`${value}T23:59:59+09:00`).getTime();
  const now = Date.now();
  return Math.ceil((deadline - now) / 86_400_000);
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

export function selected(params: Record<string, string | string[] | undefined>, key: string, value: string) {
  const current = params[key];
  return Array.isArray(current) ? current.includes(value) : current === value;
}

export function withQuery(
  params: Record<string, string | string[] | undefined>,
  changes: Record<string, string | undefined>,
) {
  const next = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (Array.isArray(value)) value.forEach((entry) => next.append(key, entry));
    else if (value) next.set(key, value);
  });
  Object.entries(changes).forEach(([key, value]) => {
    if (value) next.set(key, value);
    else next.delete(key);
  });
  return `/?${next.toString()}`;
}

/** Every query key that narrows the result set, in the order chips are shown. */
export const FILTER_KEYS = [
  "status",
  "graduation_year",
  "event_type",
  "industry",
  "job_category",
  "event_format",
] as const;

export function valuesOf(params: Record<string, string | string[] | undefined>, key: string) {
  const value = params[key];
  return Array.isArray(value) ? value : value ? [value] : [];
}

export function activeFilterCount(params: Record<string, string | string[] | undefined>) {
  return FILTER_KEYS.reduce((total, key) => total + valuesOf(params, key).length, 0);
}

/** Same params minus one filter value — used by the chips' remove links. */
export function withoutFilter(
  params: Record<string, string | string[] | undefined>,
  key: string,
  value: string,
) {
  const next = new URLSearchParams();
  Object.entries(params).forEach(([entryKey, entryValue]) => {
    if (entryKey === "page") return;
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
