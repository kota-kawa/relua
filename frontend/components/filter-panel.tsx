import Link from "next/link";

import { Filter, X } from "@/components/icons";
import type { MasterItem, Masters, SearchParams } from "@/lib/types";

function CheckboxGroup({
  title,
  name,
  items,
  current,
  limit,
}: {
  title: string;
  name: string;
  items: MasterItem[];
  current: SearchParams;
  limit?: number;
}) {
  const values = current[name];
  const selectedValues = new Set(Array.isArray(values) ? values : values ? [values] : []);
  const displayed = limit ? items.slice(0, limit) : items;
  return (
    <fieldset className="filter-group">
      <legend>{title}</legend>
      <div className="filter-options">
        {displayed.map((item) => (
          <label key={item.id} className="check-row">
            <input type="checkbox" name={name} value={item.slug} defaultChecked={selectedValues.has(item.slug)} />
            <span className="custom-check" aria-hidden="true" />
            <span>{item.name}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Fields({ masters, params }: { masters: Masters; params: SearchParams }) {
  return (
    <>
      {params.q && <input type="hidden" name="q" value={Array.isArray(params.q) ? params.q[0] : params.q} />}
      {params.view && <input type="hidden" name="view" value={Array.isArray(params.view) ? params.view[0] : params.view} />}
      <CheckboxGroup title="募集状況" name="status" items={masters.recruitment_statuses} current={params} />
      <CheckboxGroup title="卒業年度" name="graduation_year" items={masters.graduation_years} current={params} />
      <CheckboxGroup title="募集種別" name="event_type" items={masters.event_types} current={params} />
      <CheckboxGroup title="業界" name="industry" items={masters.industries} current={params} />
      <CheckboxGroup title="開催形式" name="event_format" items={masters.event_formats} current={params} />
    </>
  );
}

export function FilterPanel({ masters, params }: { masters: Masters; params: SearchParams }) {
  const activeCount = ["status", "graduation_year", "event_type", "industry", "event_format"]
    .flatMap((key) => {
      const value = params[key];
      return Array.isArray(value) ? value : value ? [value] : [];
    }).length;

  return (
    <>
      <aside className="filter-panel desktop-filter" aria-label="検索条件">
        <div className="filter-title">
          <span><Filter size={17} /> 絞り込み</span>
          {activeCount > 0 && <Link href={params.q ? `/?q=${encodeURIComponent(String(params.q))}${params.view ? `&view=${encodeURIComponent(String(params.view))}` : ""}` : params.view ? `/?view=${encodeURIComponent(String(params.view))}` : "/"}><X size={14} /> 解除</Link>}
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
