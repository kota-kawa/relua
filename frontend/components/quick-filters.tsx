import Link from "next/link";

import { Check } from "@/components/icons";
import { valuesOf, withFilter, withoutFilter } from "@/lib/format";
import type { MasterItem, Masters, SearchParams } from "@/lib/types";

/**
 * One-tap shortcuts into the industries students narrow by first. Industry is
 * deliberately the only axis here: every other filter this row used to mix in
 * (募集状況・卒業年度・募集種別・開催形式) is already expanded in the sidebar,
 * whereas the 業界 group is collapsed by default — so these chips surface
 * something that is otherwise a click away.
 *
 * These link to the `industry` filter rather than the keyword box: the
 * keyword search only covers company name, event name, description and
 * requirements (backend/app/services/opportunities.py), so `?q=IT` finds
 * nothing while `?industry=industry-01` finds every IT・通信 listing.
 *
 * Slugs are the stable master-data identifiers (see backend/app/master_data.py).
 */
const SHORTCUTS: { key: string; source: keyof Masters; slug: string; label?: string }[] = [
  { key: "industry", source: "industries", slug: "industry-01" },                     /* IT・通信 */
  { key: "industry", source: "industries", slug: "industry-02" },                     /* メーカー */
  { key: "industry", source: "industries", slug: "industry-04" },                     /* 金融 */
  /* Shortened for the chip only; the filter still applies the full master value. */
  { key: "industry", source: "industries", slug: "industry-05", label: "コンサル" },  /* コンサル・シンクタンク */
];

export function QuickFilters({ masters, params }: { masters: Masters; params: SearchParams }) {
  const chips = SHORTCUTS.flatMap((shortcut) => {
    const item = (masters[shortcut.source] as MasterItem[]).find((entry) => entry.slug === shortcut.slug);
    return item ? [{ ...shortcut, name: item.name }] : [];
  });
  if (!chips.length) return null;

  return (
    <nav className="quick-filters" aria-label="業界から探す">
      {chips.map((chip) => {
        const active = valuesOf(params, chip.key).includes(chip.slug);
        return (
          <Link
            key={`${chip.key}-${chip.slug}`}
            href={active ? withoutFilter(params, chip.key, chip.slug) : withFilter(params, chip.key, chip.slug)}
            className={active ? "active" : ""}
            aria-current={active ? "true" : undefined}
            /* The chip may be shortened; announce the full industry name. */
            aria-label={chip.label ? chip.name : undefined}
            title={chip.name}
          >
            {active && <Check size={14} aria-hidden="true" />}
            {chip.label ?? chip.name}
          </Link>
        );
      })}
    </nav>
  );
}
