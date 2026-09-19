"use client";

import { useEffect, useId, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";

import { Check, ChevronDown, SlidersHorizontal } from "@/components/icons";
import { filterHref, publicValuesOf } from "@/lib/format";
import { useReportNavigation } from "@/lib/navigation-progress";
import type { SearchParams } from "@/lib/types";

const OPTIONS = [
  { value: "relevance", label: "関連度順" },
  { value: "deadline", label: "締切が近い順" },
  { value: "updated", label: "更新が新しい順" },
  { value: "created", label: "掲載が新しい順" },
];

/**
 * The menu is a disclosure holding ordinary buttons, not an ARIA listbox.
 *
 * It used to carry role="listbox"/role="option", which promises arrow-key
 * navigation and aria-activedescendant. Neither was implemented, and Escape was
 * bound to the trigger alone, so a keyboard user who tabbed into the menu had no
 * way out of it. Plain buttons get Tab, Enter and Space from the platform; this
 * component only has to add Escape, return focus to the trigger, and close when
 * focus or a pointer leaves.
 *
 * `open` doubles as the reason it opened, so a menu summoned with the arrow keys
 * can move focus into itself while one opened by pointer leaves focus alone.
 */
type OpenState = false | "pointer" | "keyboard";

export function SortForm({ params, value }: { params: SearchParams; value: string }) {
  const router = useRouter();
  const [open, setOpen] = useState<OpenState>(false);
  const [isPending, startTransition] = useTransition();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  useReportNavigation(isPending);
  const menuId = useId();
  const hasQuery = Array.isArray(params.q) ? params.q.some(Boolean) : Boolean(params.q);
  const availableOptions = hasQuery ? OPTIONS : OPTIONS.filter((option) => option.value !== "relevance");
  const current = availableOptions.find((option) => option.value === value) ?? availableOptions[0];

  useEffect(() => {
    if (!open) return;
    const closeWhenOutside = (event: Event) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeWhenOutside);
    /* Tabbing past the last option never produces a pointer event, so focus
       moving out of the menu has to close it as well. */
    document.addEventListener("focusin", closeWhenOutside);
    return () => {
      document.removeEventListener("pointerdown", closeWhenOutside);
      document.removeEventListener("focusin", closeWhenOutside);
    };
  }, [open]);

  useEffect(() => {
    if (open !== "keyboard") return;
    menuRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [open]);

  function closeMenu({ returnFocus }: { returnFocus: boolean }) {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }

  function sortHref(sort: string) {
    const entries = Object.keys(params).flatMap((key) => {
      if (key === "sort" || key === "page") return [];
      const list = publicValuesOf(params, key);
      return list.map((item) => [key, item] as [string, string]);
    });
    entries.push(["sort", sort]);
    return filterHref(entries, false);
  }

  function selectSort(sort: string) {
    /* The chosen option unmounts with the menu, so focus has to go somewhere
       deliberate rather than falling back to <body>. */
    closeMenu({ returnFocus: true });
    if (sort === value) return;
    startTransition(() => router.replace(sortHref(sort), { scroll: false }));
  }

  return (
    <div
      className={`sort-form${isPending ? " is-pending" : ""}`}
      ref={rootRef}
      /* Bound on the wrapper rather than the trigger so Escape also works once
         focus has moved into the menu. */
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !open) return;
        event.stopPropagation();
        closeMenu({ returnFocus: true });
      }}
    >
      <button
        type="button"
        ref={triggerRef}
        className="sort-trigger"
        aria-label={`並び替え: ${current.label}`}
        aria-controls={menuId}
        aria-expanded={Boolean(open)}
        onClick={() => setOpen((shown) => (shown ? false : "pointer"))}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen("keyboard");
          }
        }}
      >
        <SlidersHorizontal className="sort-form-icon" size={15} aria-hidden="true" />
        <span>{current.label}</span>
        <ChevronDown className="sort-select-chevron" size={15} aria-hidden="true" />
      </button>
      {open && (
        <div className="sort-menu" id={menuId} ref={menuRef} aria-label="並び順">
          {availableOptions.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-current={option.value === value}
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
          {Object.keys(params).flatMap((key) => {
            if (key === "sort" || key === "page") return [];
            const list = publicValuesOf(params, key);
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
