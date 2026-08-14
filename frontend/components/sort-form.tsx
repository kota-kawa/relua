"use client";

import { useEffect, useId, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Check, ChevronDown, SlidersHorizontal } from "@/components/icons";
import { filterHref } from "@/lib/format";
import type { SearchParams } from "@/lib/types";

const OPTIONS = [
  { value: "relevance", label: "関連度順" },
  { value: "deadline", label: "締切が近い順" },
  { value: "updated", label: "更新が新しい順" },
  { value: "created", label: "掲載が新しい順" },
];

export function SortForm({ params, value }: { params: SearchParams; value: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [isPending, startTransition] = useTransition();
  const rootRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const hasQuery = Array.isArray(params.q) ? params.q.some(Boolean) : Boolean(params.q);
  const availableOptions = hasQuery ? OPTIONS : OPTIONS.filter((option) => option.value !== "relevance");
  const current = availableOptions.find((option) => option.value === value) ?? availableOptions[0];

  useEffect(() => {
    if (!open) return;
    const closeWhenOutside = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeWhenOutside);
    return () => document.removeEventListener("pointerdown", closeWhenOutside);
  }, [open]);

  function sortHref(sort: string) {
    const entries = Object.entries(params).flatMap(([key, entry]) => {
      if (key === "sort" || key === "page") return [];
      const list = Array.isArray(entry) ? entry : entry ? [entry] : [];
      return list.map((item) => [key, item] as [string, string]);
    });
    entries.push(["sort", sort]);
    return filterHref(entries, false);
  }

  function selectSort(sort: string) {
    setOpen(false);
    if (sort === value) return;
    startTransition(() => router.replace(sortHref(sort), { scroll: false }));
  }

  return (
    <div className={`sort-form${isPending ? " is-pending" : ""}`} ref={rootRef}>
      <button
        type="button"
        className="sort-trigger"
        aria-label={`並び替え: ${current.label}`}
        aria-haspopup="listbox"
        aria-controls={menuId}
        aria-expanded={open}
        onClick={() => setOpen((shown) => !shown)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        <SlidersHorizontal className="sort-form-icon" size={15} aria-hidden="true" />
        <span>{current.label}</span>
        <ChevronDown className="sort-select-chevron" size={15} aria-hidden="true" />
      </button>
      {open && (
        <div className="sort-menu" id={menuId} role="listbox" aria-label="並び順">
          {availableOptions.map((option) => (
            <button
              key={option.value}
              type="button"
              role="option"
              aria-selected={option.value === value}
              className={option.value === value ? "active" : ""}
              onClick={() => selectSort(option.value)}
            >
              <span>{option.label}</span>
              {option.value === value && <Check size={15} aria-hidden="true" />}
            </button>
          ))}
        </div>
      )}
      <noscript>
        <form action="/" method="get">
          {Object.entries(params).flatMap(([key, entry]) => {
            if (key === "sort" || key === "page") return [];
            const list = Array.isArray(entry) ? entry : entry ? [entry] : [];
            return list.map((item) => <input key={`${key}-${item}`} type="hidden" name={key} value={item} />);
          })}
          <label htmlFor="sort">並び替え</label>
          <select id="sort" name="sort" defaultValue={current.value}>{availableOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
          <button type="submit">適用</button>
        </form>
      </noscript>
    </div>
  );
}
