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
    <>
      {/* The bar itself is sticky, and a stuck element already sits at the top
          of the viewport — scrolling to it would either move nothing or, as the
          router skips sticky elements when resolving a hash, land on the
          section below and leave the results heading hidden behind the bar.
          This in-flow marker gives `#listings` a stable position: the point
          where the bar comes to rest and the results begin. */}
      <div id="listings" className="listings-anchor" aria-hidden="true" />
      <div className="discovery-bar">
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
    </>
  );
}
