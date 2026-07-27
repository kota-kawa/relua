import Link from "next/link";

import { Filter, X } from "@/components/icons";
import { activeFilterCount, valuesOf, withoutAllFilters } from "@/lib/format";
import type { MasterItem, Masters, SearchParams } from "@/lib/types";

function CheckboxGroup({
  title,
  name,
  items,
  current,
  /** Long lists start collapsed so the panel stays scannable. */
  collapsed,
}: {
  title: string;
  name: string;
  items: MasterItem[];
  current: SearchParams;
  collapsed?: boolean;
}) {
  const selectedValues = new Set(valuesOf(current, name));
  const options = items.map((item) => (
    <label key={item.id} className="check-row">
      <input type="checkbox" name={name} value={item.slug} defaultChecked={selectedValues.has(item.slug)} />
      <span className="custom-check" aria-hidden="true" />
      <span>{item.name}</span>
    </label>
  ));

  if (!collapsed) {
    return (
      <fieldset className="filter-group">
        <legend>{title}</legend>
        <div className="filter-options">{options}</div>
      </fieldset>
    );
  }

  const chosen = items.filter((item) => selectedValues.has(item.slug)).length;
  return (
    <details className="filter-group filter-group-collapsible" open={chosen > 0}>
      <summary>
        {title}
        {chosen > 0 ? <b>{chosen}</b> : <small>{items.length}</small>}
      </summary>
      <div className="filter-options">{options}</div>
    </details>
  );
}

function Fields({ masters, params }: { masters: Masters; params: SearchParams }) {
  return (
    <>
      {valuesOf(params, "q").map((value) => <input key={`q-${value}`} type="hidden" name="q" value={value} />)}
      {valuesOf(params, "view").map((value) => <input key={`view-${value}`} type="hidden" name="view" value={value} />)}
      {valuesOf(params, "sort").map((value) => <input key={`sort-${value}`} type="hidden" name="sort" value={value} />)}
      <CheckboxGroup title="募集状況" name="status" items={masters.recruitment_statuses} current={params} />
      <CheckboxGroup title="卒業年度" name="graduation_year" items={masters.graduation_years} current={params} />
      <CheckboxGroup title="募集種別" name="event_type" items={masters.event_types} current={params} />
      <CheckboxGroup title="職種" name="job_category" items={masters.job_categories} current={params} collapsed />
      <CheckboxGroup title="業界" name="industry" items={masters.industries} current={params} collapsed />
      <CheckboxGroup title="業種" name="sector" items={masters.sectors} current={params} collapsed />
      <CheckboxGroup title="対象学位" name="degree" items={masters.degrees} current={params} collapsed />
      <CheckboxGroup title="開催形式" name="event_format" items={masters.event_formats} current={params} collapsed />
    </>
  );
}

export function FilterPanel({ masters, params }: { masters: Masters; params: SearchParams }) {
  const activeCount = activeFilterCount(params);

  return (
    <>
      <aside className="filter-panel desktop-filter" aria-label="検索条件">
        <div className="filter-title">
          <span><Filter size={17} /> 絞り込み</span>
          {activeCount > 0 && (
            <Link href={withoutAllFilters(params)}><X size={14} /> 解除</Link>
          )}
        </div>
        <form action="/" method="get">
          <Fields masters={masters} params={params} />
          <button className="filter-submit" type="submit">この条件で表示</button>
        </form>
      </aside>

      <details className="mobile-filter">
        <summary><Filter size={17} /> 絞り込み {activeCount > 0 && <b>{activeCount}</b>}</summary>
        <form action="/" method="get" className="mobile-filter-body">
          <Fields masters={masters} params={params} />
          <button className="filter-submit" type="submit">この条件で表示</button>
        </form>
      </details>
    </>
  );
}
