import Link from "next/link";

import { CalendarRange, Grid2X2, List } from "@/components/icons";
import type { SearchParams } from "@/lib/types";

type ViewMode = "cards" | "list" | "calendar";

function values(params: SearchParams, key: string) {
  const value = params[key];
  return Array.isArray(value) ? value : value ? [value] : [];
}

function hrefFor(
  params: SearchParams,
  changes: { eventTypes?: string[]; view?: ViewMode },
) {
  const next = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (["event_type", "view", "page"].includes(key)) return;
    if (Array.isArray(value)) value.forEach((entry) => next.append(key, entry));
    else if (value) next.set(key, value);
  });
  changes.eventTypes?.forEach((value) => next.append("event_type", value));
  if (changes.view && changes.view !== "cards") next.set("view", changes.view);
  const query = next.toString();
  return query ? `/?${query}#listings` : "/#listings";
}

const categories = [
  { label: "すべて", eventTypes: [] },
  { label: "インターン", eventTypes: ["type-01"] },
  { label: "本選考", eventTypes: ["type-02"] },
  { label: "説明会・イベント", eventTypes: ["type-03", "type-05"] },
] as const;

export function DiscoveryNav({ params, view }: { params: SearchParams; view: ViewMode }) {
  const selectedTypes = values(params, "event_type").sort();
  return (
    <div className="discovery-bar" id="listings">
      <div className="shell discovery-inner">
        <nav className="category-tabs" aria-label="募集カテゴリ">
          {categories.map((category) => {
            const categoryTypes = [...category.eventTypes].sort();
            const active = view !== "calendar"
              && selectedTypes.length === categoryTypes.length
              && selectedTypes.every((value, index) => value === categoryTypes[index]);
            return (
              <Link
                key={category.label}
                href={hrefFor(params, { eventTypes: [...category.eventTypes], view: view === "calendar" ? "cards" : view })}
                className={active ? "active" : ""}
                aria-current={active ? "page" : undefined}
              >
                {category.label}
              </Link>
            );
          })}
          <Link
            href={hrefFor(params, { eventTypes: [], view: "calendar" })}
            className={`calendar-tab ${view === "calendar" ? "active" : ""}`}
            aria-current={view === "calendar" ? "page" : undefined}
          >
            <CalendarRange size={16} /> 締切カレンダー
          </Link>
        </nav>

        <nav className="view-switcher" aria-label="表示形式">
          <Link
            href={hrefFor(params, { eventTypes: selectedTypes, view: "cards" })}
            className={view === "cards" ? "active" : ""}
            aria-label="カード表示"
            title="カード表示"
          >
            <Grid2X2 size={16} /> <span>カード</span>
          </Link>
          <Link
            href={hrefFor(params, { eventTypes: selectedTypes, view: "list" })}
            className={view === "list" ? "active" : ""}
            aria-label="一覧表示"
            title="一覧表示"
          >
            <List size={17} /> <span>一覧</span>
          </Link>
        </nav>
      </div>
    </div>
  );
}
