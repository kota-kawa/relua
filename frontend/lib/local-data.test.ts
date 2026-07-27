import { describe, expect, it } from "vitest";

import {
  bookmarkCsv,
  bookmarkJson,
  buildFragmentUrl,
  mergeBookmarks,
  normalizeIds,
  parseBookmarkFile,
  parseFragmentIds,
  readBookmarks,
  recordRecent,
  removeBookmarks,
  toggleBookmark,
} from "./local-data";

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => { data.set(key, value); },
    removeItem: (key: string) => { data.delete(key); },
  };
}

describe("local bookmark data", () => {
  it("validates and deduplicates identifiers", () => {
    expect(normalizeIds([125, "391", "391", "../../x", "", null])).toEqual(["125", "391"]);
  });

  it("toggles, merges and removes without duplicates", () => {
    const storage = memoryStorage();
    expect(toggleBookmark(storage, "1").saved).toBe(true);
    expect(mergeBookmarks(storage, ["1", "2", "3"])).toEqual(["1", "2", "3"]);
    expect(toggleBookmark(storage, "2").saved).toBe(false);
    expect(removeBookmarks(storage, ["3"])).toEqual(["1"]);
    expect(readBookmarks(storage)).toEqual(["1"]);
  });

  it("keeps recent items unique and newest first", () => {
    const storage = memoryStorage();
    recordRecent(storage, "one", "2026-07-26T00:00:00Z");
    const recents = recordRecent(storage, "one", "2026-07-27T00:00:00Z");
    expect(recents).toEqual([{ id: "one", viewedAt: "2026-07-27T00:00:00Z" }]);
  });

  it("round-trips fragment URLs", () => {
    const url = buildFragmentUrl("https://example.com/current", "/import", "b", ["125", "391"]);
    expect(url).toBe("https://example.com/import#b=125,391");
    expect(parseFragmentIds(new URL(url).hash, "b")).toEqual(["125", "391"]);
  });

  it("exports and validates JSON and CSV backups", () => {
    const json = bookmarkJson(["1", "2"], "2026-07-27T10:00:00+09:00");
    expect(parseBookmarkFile(json, "backup.json")).toEqual(["1", "2"]);
    expect(parseBookmarkFile(bookmarkCsv(["1", "2"]), "backup.csv")).toEqual(["1", "2"]);
    expect(parseBookmarkFile('{"version":2,"bookmarks":[1]}', "backup.json")).toEqual([]);
  });
});
