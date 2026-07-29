"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";

import { Bookmark } from "@/components/icons";
import { BOOKMARKS_KEY, LOCAL_DATA_EVENT, normalizeIds } from "@/lib/local-data";

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener(LOCAL_DATA_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(LOCAL_DATA_EVENT, callback);
  };
}

function snapshot() {
  try { return window.localStorage.getItem(BOOKMARKS_KEY) ?? "[]"; } catch { return "[]"; }
}

export function SavedNavigation() {
  const raw = useSyncExternalStore(subscribe, snapshot, () => "[]");
  let count = 0;
  try { count = normalizeIds(JSON.parse(raw)).length; } catch { count = 0; }
  return (
    <Link className="saved-navigation" href="/saved">
      <Bookmark size={17} /> 保存した募集
      {count > 0 && <b>{count}</b>}
    </Link>
  );
}
