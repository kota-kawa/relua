import Link from "next/link";

import { ActiveFilters } from "@/components/active-filters";
import { CalendarRange, Grid2X2, List } from "@/components/icons";
import { publicValuesOf } from "@/lib/format";
import type { Masters, SearchParams } from "@/lib/types";

export type ViewMode = "cards" | "list" | "calendar";

/**
 * Only the view changes — every filter and the keyword are carried over.
 * (Switching to the calendar used to silently reset the selected event types.)
 */
function viewHref(params: SearchParams, view: ViewMode) {
  const next = new URLSearchParams();
  Object.entries(params).forEach(([key]) => {
    if (key === "view" || key === "page") return;
    const list = publicValuesOf(params, key);
    list.forEach((entry) => next.append(key, entry));
  });
  if (view !== "cards") next.set("view", view);
  const query = next.toString();
  return query ? `/?${query}#listings` : "/#listings";
}

const VIEWS: { mode: ViewMode; label: string; icon: React.ReactNode }[] = [
  { mode: "cards", label: "カード", icon: <Grid2X2 size={16} /> },
  { mode: "list", label: "一覧", icon: <List size={17} /> },
  { mode: "calendar", label: "締切順", icon: <CalendarRange size={16} /> },
];

export function DiscoveryNav({
  masters,
  params,
  view,
  total,
}: {
  masters: Masters;
  params: SearchParams;
  view: ViewMode;
  total: number;
}) {
  return (
    <div className="discovery-bar" id="listings">
      <div className="shell discovery-inner">
        <ActiveFilters masters={masters} params={params} total={total} />
        <nav className="view-switcher" aria-label="表示形式">
          {VIEWS.map((entry) => (
            <Link
              key={entry.mode}
              href={viewHref(params, entry.mode)}
              className={view === entry.mode ? "active" : ""}
              aria-current={view === entry.mode ? "page" : undefined}
              title={`${entry.label}表示`}
            >
              {entry.icon} <span>{entry.label}</span>
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}
