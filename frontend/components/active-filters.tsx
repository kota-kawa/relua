import { X } from "@/components/icons";
import { NavLink } from "@/components/nav-link";
import { FILTER_KEYS, hasDefaultOpenStatus, labelledSectors, valuesOf, withoutAllFilters, withoutFilter } from "@/lib/format";
import type { MasterItem, Masters, SearchParams } from "@/lib/types";

const GROUP_LABEL: Record<string, string> = {
  status: "募集状況",
  graduation_year: "卒業年度",
  event_type: "募集種別",
  industry: "業界",
  sector: "業種",
  job_category: "職種",
  degree: "対象学位",
  event_format: "開催形式",
};

const GROUP_SOURCE: Record<string, keyof Masters> = {
  status: "recruitment_statuses",
  graduation_year: "graduation_years",
  event_type: "event_types",
  industry: "industries",
  sector: "sectors",
  job_category: "job_categories",
  degree: "degrees",
  event_format: "event_formats",
};

/**
 * The one place that shows what the result set is currently narrowed by.
 * Before this existed the state lived only in the sidebar checkboxes, which are
 * collapsed on mobile — so applied filters were effectively invisible there.
 */
export function ActiveFilters({ masters, params, total }: { masters: Masters; params: SearchParams; total: number }) {
  const defaultOpenStatus = hasDefaultOpenStatus(params);
  const chips = FILTER_KEYS.flatMap((key) => {
    if (key === "status" && defaultOpenStatus) return [];
    /* Sectors share the panel's disambiguated labels, so a chip never reads
       just "業種 その他" with no clue which industry's それ it is. */
    const items = key === "sector" ? labelledSectors(masters) : (masters[GROUP_SOURCE[key]] as MasterItem[]);
    return valuesOf(params, key).map((slug) => ({
      key,
      slug,
      group: GROUP_LABEL[key],
      name: items.find((item) => item.slug === slug)?.name ?? slug,
    }));
  });

  const query = valuesOf(params, "q")[0];

  if (!chips.length && !query) {
    return (
      <p className="filter-summary">
        <strong>{total.toLocaleString("ja-JP")}</strong> 件の募集をすべて表示中
      </p>
    );
  }

  return (
    <>
      {/* Mobile puts the chips on their own row; this keeps the count on the first one. */}
      <p className="filter-summary filter-summary-compact">
        <strong>{total.toLocaleString("ja-JP")}</strong> 件
      </p>
      <div className="active-filters">
        <span className="active-filters-label">絞り込み中</span>
        <ul>
          {query && (
            <li>
              <NavLink href={withoutFilter(params, "q", query)}>
                <b>キーワード</b> {query}
                <X size={13} aria-label="この条件を外す" />
              </NavLink>
            </li>
          )}
          {chips.map((chip) => (
            <li key={`${chip.key}-${chip.slug}`}>
              <NavLink href={withoutFilter(params, chip.key, chip.slug)}>
                <b>{chip.group}</b> {chip.name}
                <X size={13} aria-label="この条件を外す" />
              </NavLink>
            </li>
          ))}
        </ul>
        {chips.length > 0 && (
          <NavLink className="clear-all" href={withoutAllFilters(params)}>
            すべて解除
          </NavLink>
        )}
      </div>
    </>
  );
}
