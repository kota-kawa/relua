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
