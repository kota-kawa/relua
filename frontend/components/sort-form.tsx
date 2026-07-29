"use client";

import { ChevronDown, SlidersHorizontal } from "@/components/icons";
import type { SearchParams } from "@/lib/types";

const OPTIONS = [
  { value: "deadline", label: "締切が近い順" },
  { value: "updated", label: "更新が新しい順" },
  { value: "created", label: "掲載が新しい順" },
];

export function SortForm({ params, value }: { params: SearchParams; value: string }) {
  return (
    <form action="/" method="get" className="sort-form">
      {Object.entries(params).flatMap(([key, entry]) => {
        if (key === "sort" || key === "page") return [];
        const list = Array.isArray(entry) ? entry : entry ? [entry] : [];
        return list.map((item) => <input key={`${key}-${item}`} type="hidden" name={key} value={item} />);
      })}
      <span className="sort-form-icon" aria-hidden="true"><SlidersHorizontal size={15} /></span>
      <label htmlFor="sort" className="sort-form-label">並び替え</label>
      <span className="sort-select-wrap">
        <select
          id="sort"
          name="sort"
          defaultValue={value}
          onChange={(event) => event.currentTarget.form?.requestSubmit()}
        >
          {OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <ChevronDown className="sort-select-chevron" size={15} aria-hidden="true" />
      </span>
      {/* Selecting an option submits directly; the button is only a no-JS fallback. */}
      <noscript>
        <button type="submit">適用</button>
      </noscript>
    </form>
  );
}
