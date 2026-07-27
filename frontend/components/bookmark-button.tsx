"use client";

import { useSyncExternalStore } from "react";

import { Bookmark } from "@/components/icons";
import { showToast } from "@/components/toast";
import { BOOKMARKS_KEY, LOCAL_DATA_EVENT, normalizeIds, toggleBookmark } from "@/lib/local-data";

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener(LOCAL_DATA_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(LOCAL_DATA_EVENT, callback);
  };
}

function snapshot() {
  return window.localStorage.getItem(BOOKMARKS_KEY) ?? "[]";
}

function idsFromSnapshot(value: string) {
  try {
    return normalizeIds(JSON.parse(value));
  } catch {
    return [];
  }
}

export function notifyLocalDataChanged() {
  window.dispatchEvent(new Event(LOCAL_DATA_EVENT));
}

export function BookmarkButton({ id, compact = false }: { id: string; compact?: boolean }) {
  const raw = useSyncExternalStore(subscribe, snapshot, () => "[]");
  const saved = idsFromSnapshot(raw).includes(id);

  return (
    <button
      type="button"
      className={`bookmark-button${saved ? " saved" : ""}${compact ? " compact" : ""}`}
      aria-pressed={saved}
      aria-label={saved ? "保存を解除" : "保存"}
      title={saved ? "保存を解除" : "保存"}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        toggleBookmark(window.localStorage, id);
        notifyLocalDataChanged();
        if (saved) showToast("保存を解除しました");
        /* Linking back to /saved from /saved would be noise. */
        else if (window.location.pathname.startsWith("/saved")) showToast("保存しました");
        else showToast("保存しました", { label: "保存一覧を見る", href: "/saved" });
      }}
    >
      <Bookmark size={compact ? 17 : 18} fill={saved ? "currentColor" : "none"} />
      {!compact && <span>{saved ? "保存済み" : "保存"}</span>}
    </button>
  );
}
