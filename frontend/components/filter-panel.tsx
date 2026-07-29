"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useTransition, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { Filter, X } from "@/components/icons";
import {
  FILTER_KEYS,
  activeFilterCount,
  actionableFilterItems,
  ALL_STATUS_SCOPE,
  currentGraduationYears,
  filterHref,
  valuesOf,
  withoutAllFilters,
} from "@/lib/format";
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

function IndustryGroup({ masters, current }: { masters: Masters; current: SearchParams }) {
  const selectedIndustries = new Set(valuesOf(current, "industry"));
  const selectedSectors = new Set(valuesOf(current, "sector"));
  const selectedIndustryIds = new Set(
    masters.industries.filter((item) => selectedIndustries.has(item.slug)).map((item) => item.id),
  );
  const chosen = selectedIndustries.size + selectedSectors.size;

  return (
    <details className="filter-group filter-group-collapsible" open>
      <summary>
        業界
        {chosen > 0 ? <b>{chosen}</b> : <small>{masters.industries.length}</small>}
      </summary>
      <div className="filter-options industry-tree">
        {masters.industries.map((industry) => {
          const selected = selectedIndustries.has(industry.slug);
          const sectors = actionableFilterItems(
            masters.sectors.filter((sector) => sector.industry_id === industry.id),
            valuesOf(current, "sector"),
          );
          return (
            <div className="industry-branch" key={industry.id}>
              <label className="check-row industry-parent">
                <input type="checkbox" name="industry" value={industry.slug} defaultChecked={selected} />
                <span className="custom-check" aria-hidden="true" />
                <span>{industry.name}</span>
              </label>
              {selected && sectors.length > 0 && (
                <div className="industry-children" role="group" aria-label={`${industry.name}の詳細`}>
                  <small>さらに絞り込む</small>
                  {sectors.map((sector) => (
                    <label className="check-row" key={sector.id}>
                      <input
                        type="checkbox"
                        name="sector"
                        value={sector.slug}
                        defaultChecked={selectedSectors.has(sector.slug)}
                      />
                      <span className="custom-check" aria-hidden="true" />
                      <span>{sector.name}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {/* Shared URLs may contain a sector without its parent industry. Preserve
          those legacy values until the user removes their applied-filter chip. */}
      {masters.sectors
        .filter((sector) => selectedSectors.has(sector.slug) && !selectedIndustryIds.has(sector.industry_id))
        .map((sector) => <input key={sector.slug} type="hidden" name="sector" value={sector.slug} />)}
    </details>
  );
}

function Fields({ masters, params }: { masters: Masters; params: SearchParams }) {
  return (
    <>
      {valuesOf(params, "q").map((value) => <input key={`q-${value}`} type="hidden" name="q" value={value} />)}
      {valuesOf(params, "view").map((value) => <input key={`view-${value}`} type="hidden" name="view" value={value} />)}
      {valuesOf(params, "sort").map((value) => <input key={`sort-${value}`} type="hidden" name="sort" value={value} />)}
      {valuesOf(params, "status_scope").map((value) => <input key={`status-scope-${value}`} type="hidden" name="status_scope" value={value} />)}
      {/* Keep advanced URL filters intact when a visible filter is changed. They
          remain removable from the applied-filter chips, but do not crowd the
          primary discovery controls. */}
      {(["status", "job_category", "degree", "event_format"] as const).flatMap((name) => (
        valuesOf(params, name).map((value) => <input key={`${name}-${value}`} type="hidden" name={name} value={value} />)
      ))}
      <CheckboxGroup
        title="卒業年度"
        name="graduation_year"
        items={currentGraduationYears(masters.graduation_years, valuesOf(params, "graduation_year"))}
        current={params}
      />
      <CheckboxGroup
        title="募集種別"
        name="event_type"
        items={actionableFilterItems(masters.event_types, valuesOf(params, "event_type"))}
        current={params}
      />
      <IndustryGroup masters={masters} current={params} />
    </>
  );
}

export function FilterPanel({ masters, params, total }: { masters: Masters; params: SearchParams; total: number }) {
  const activeCount = activeFilterCount(params);
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [sheetOpen, setSheetOpen] = useState(false);
  const sheetRef = useRef<HTMLDialogElement>(null);

  /* The sheet is a native <dialog>: focus trap, Escape and backdrop come free. */
  useEffect(() => {
    const sheet = sheetRef.current;
    if (!sheet) return;
    if (sheetOpen && !sheet.open) sheet.showModal();
    else if (!sheetOpen && sheet.open) sheet.close();
  }, [sheetOpen]);

  function applyFilters(form: HTMLFormElement, changedInput?: HTMLInputElement) {
    let entries = Array.from(new FormData(form).entries()).flatMap(([key, value]) => (
      typeof value === "string" ? [[key, value] as [string, string]] : []
    ));
    if (changedInput?.name === "industry" && !changedInput.checked) {
      const industry = masters.industries.find((item) => item.slug === changedInput.value);
      const childSlugs = new Set(
        masters.sectors.filter((sector) => sector.industry_id === industry?.id).map((sector) => sector.slug),
      );
      entries = entries.filter(([key, value]) => key !== "sector" || !childSlugs.has(value));
    }
    const hasStatus = entries.some(([key]) => key === "status");
    entries = entries.filter(([key]) => key !== "status_scope");
    if (!hasStatus) entries.push(["status_scope", ALL_STATUS_SCOPE]);
    startTransition(() => router.replace(filterHref(entries), { scroll: false }));
  }

  function handleChange(event: FormEvent<HTMLFormElement>) {
    const target = event.target;
    if (target instanceof HTMLInputElement && target.type === "checkbox") applyFilters(event.currentTarget, target);
  }

  /* Checkboxes are uncontrolled; remounting the form when the URL's filters
     change keeps them in sync with "clear" links clicked outside the form. */
  const fieldsKey = FILTER_KEYS.map((key) => valuesOf(params, key).join(",")).join("|");

  return (
    <>
      <aside className={`filter-panel desktop-filter${isPending ? " is-updating" : ""}`} aria-label="検索条件" aria-busy={isPending}>
        <div className="filter-title">
          <span><Filter size={17} /> 絞り込み</span>
          {isPending && <small className="filter-updating" role="status">更新中…</small>}
          {activeCount > 0 && (
            <Link href={withoutAllFilters(params)}><X size={14} /> 解除</Link>
          )}
        </div>
        <form key={fieldsKey} action="/" method="get" onChange={handleChange} onSubmit={(event) => { event.preventDefault(); applyFilters(event.currentTarget); }}>
          <Fields masters={masters} params={params} />
          <noscript><button className="filter-submit" type="submit">この条件で表示</button></noscript>
        </form>
      </aside>

      <button type="button" className="filter-fab" onClick={() => setSheetOpen(true)}>
        <Filter size={18} /> 絞り込み
        {activeCount > 0 && <b>{activeCount}</b>}
      </button>

      <dialog
        ref={sheetRef}
        className="filter-sheet"
        aria-label="検索条件"
        onClose={() => setSheetOpen(false)}
        onPointerDown={(event) => { if (event.target === event.currentTarget) setSheetOpen(false); }}
      >
        <header className="filter-sheet-header">
          <span><Filter size={17} /> 絞り込み</span>
          {activeCount > 0 && (
            <Link className="filter-sheet-clear" href={withoutAllFilters(params)}><X size={14} /> すべて解除</Link>
          )}
          <button type="button" className="panel-close" onClick={() => setSheetOpen(false)} aria-label="閉じる"><X size={18} /></button>
        </header>
        <form
          key={fieldsKey}
          action="/"
          method="get"
          className={isPending ? "is-updating" : ""}
          aria-busy={isPending}
          onChange={handleChange}
          onSubmit={(event) => { event.preventDefault(); applyFilters(event.currentTarget); }}
        >
          <div className="filter-sheet-body">
            <Fields masters={masters} params={params} />
          </div>
          {/* Every checkbox applies instantly; this button reports the live count and closes the sheet. */}
          <footer className="filter-sheet-footer">
            <button type="button" className="filter-sheet-apply" onClick={() => setSheetOpen(false)}>
              {isPending ? "検索中…" : `${total.toLocaleString("ja-JP")}件を表示`}
            </button>
          </footer>
        </form>
      </dialog>

      <noscript>
        <details className="mobile-filter">
          <summary><Filter size={17} /> 絞り込み {activeCount > 0 && <b>{activeCount}</b>}</summary>
          <form action="/" method="get" className="mobile-filter-body">
            <Fields masters={masters} params={params} />
            <button className="filter-submit" type="submit">この条件で表示</button>
          </form>
        </details>
      </noscript>
    </>
  );
}
