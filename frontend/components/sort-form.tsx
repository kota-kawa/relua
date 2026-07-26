"use client";

import { SlidersHorizontal } from "@/components/icons";
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
      <SlidersHorizontal size={16} aria-hidden="true" />
      <label htmlFor="sort" className="sr-only">並び順</label>
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
      {/* Selecting an option submits directly; the button is only a no-JS fallback. */}
      <noscript>
        <button type="submit">適用</button>
      </noscript>
    </form>
  );
}
