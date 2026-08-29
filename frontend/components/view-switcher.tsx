"use client";

import { useState } from "react";

import { CalendarRange, Grid2X2, List } from "@/components/icons";
import { NavLink } from "@/components/nav-link";
import { publicValuesOf } from "@/lib/format";
import { useNavigationPending } from "@/lib/navigation-progress";
import type { SearchParams } from "@/lib/types";

export type ViewMode = "cards" | "list" | "calendar";

const VIEWS: { mode: ViewMode; label: string; icon: React.ReactNode }[] = [
  { mode: "cards", label: "カード", icon: <Grid2X2 size={16} /> },
  { mode: "list", label: "一覧", icon: <List size={17} /> },
  { mode: "calendar", label: "締切順", icon: <CalendarRange size={16} /> },
];

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

/**
 * The three views share one highlight that slides between them, and it moves on
 * the click rather than on the answer: switching view refetches the whole
 * result set, and a control that only responds once the new page arrives reads
 * as a control that missed the press.
 *
 * The anticipated view is only honoured while a navigation is actually in
 * flight, and only for a press made from the view that is still on screen.
 * Outside that window the URL decides, so a cancelled navigation cannot leave
 * the highlight parked on a view the page never opened.
 */
export function ViewSwitcher({ params, view }: { params: SearchParams; view: ViewMode }) {
  const [chosen, setChosen] = useState<{ mode: ViewMode; from: ViewMode } | null>(null);
  const pending = useNavigationPending();
  const active = pending && chosen?.from === view ? chosen.mode : view;
  const activeIndex = VIEWS.findIndex((entry) => entry.mode === active);

  return (
    <nav
      className="view-switcher"
      aria-label="表示形式"
      style={{ "--view-index": Math.max(activeIndex, 0) } as React.CSSProperties}
    >
      <span className="view-switcher-thumb" aria-hidden="true" />
      {VIEWS.map((entry) => (
        <NavLink
          key={entry.mode}
          href={viewHref(params, entry.mode)}
          className={active === entry.mode ? "active" : ""}
          /* The highlight above runs ahead of the router; this one states which
             page is actually open, so it waits for the page to be it. */
          aria-current={view === entry.mode ? "page" : undefined}
          title={`${entry.label}表示`}
          onClick={() => setChosen({ mode: entry.mode, from: view })}
        >
          {entry.icon} <span>{entry.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
