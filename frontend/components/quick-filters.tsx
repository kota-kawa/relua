import Link from "next/link";

import { Check } from "@/components/icons";
import { valuesOf, withFilter, withoutFilter } from "@/lib/format";
import type { MasterItem, Masters, SearchParams } from "@/lib/types";

/**
 * One-tap shortcuts for the most common narrowing choices, so mobile users
 * can filter without opening the full checkbox sheet. Slugs are the stable
 * master-data identifiers (see backend/app/master_data.py).
 */
const SHORTCUTS: { key: string; source: keyof Masters; slug: string }[] = [
  { key: "status", source: "recruitment_statuses", slug: "status-02" }, /* 募集中 */
  { key: "event_type", source: "event_types", slug: "type-01" },        /* インターン */
  { key: "event_type", source: "event_types", slug: "type-02" },        /* 本選考 */
  { key: "graduation_year", source: "graduation_years", slug: "grad-01" },
  { key: "graduation_year", source: "graduation_years", slug: "grad-02" },
  { key: "event_format", source: "event_formats", slug: "format-01" },  /* オンライン */
];

export function QuickFilters({ masters, params }: { masters: Masters; params: SearchParams }) {
  const chips = SHORTCUTS.flatMap((shortcut) => {
    const item = (masters[shortcut.source] as MasterItem[]).find((entry) => entry.slug === shortcut.slug);
    return item ? [{ ...shortcut, name: item.name }] : [];
  });
  if (!chips.length) return null;

  return (
    <nav className="quick-filters" aria-label="よく使う絞り込み">
      {chips.map((chip) => {
        const active = valuesOf(params, chip.key).includes(chip.slug);
        return (
          <Link
            key={`${chip.key}-${chip.slug}`}
            href={active ? withoutFilter(params, chip.key, chip.slug) : withFilter(params, chip.key, chip.slug)}
            className={active ? "active" : ""}
            aria-current={active ? "true" : undefined}
          >
            {active && <Check size={14} aria-hidden="true" />}
            {chip.name}
          </Link>
        );
      })}
    </nav>
  );
}
