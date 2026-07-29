import { describe, expect, it } from "vitest";

import {
  bookmarkCsv,
  bookmarkJson,
  buildFragmentUrl,
  calendarDetails,
  mergeBookmarks,
  newBookmarkIds,
  normalizeIds,
  parseBookmarkFile,
  parseFragmentIds,
  readBookmarks,
  recordRecent,
  removeBookmarks,
  toggleBookmark,
  urlFitsTransferLimit,
} from "./local-data";
import type { Opportunity } from "./types";

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

  it("calculates only bookmarks that will actually be added", () => {
    expect(newBookmarkIds(["1", "2", "2", "3"], ["1", "4"])).toEqual(["2", "3"]);
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

  it("measures transfer limits in encoded bytes", () => {
    expect(urlFitsTransferLimit("a", 1)).toBe(true);
    expect(urlFitsTransferLimit("あ", 1)).toBe(false);
    const uuidIds = Array.from({ length: 55 }, (_, index) => `${String(index).padStart(8, "0")}-aaaa-4aaa-8aaa-${String(index).padStart(12, "0")}`);
    expect(urlFitsTransferLimit(buildFragmentUrl("https://example.com", "/import", "b", uuidIds))).toBe(false);
  });

  it("exports and validates JSON and CSV backups", () => {
    const json = bookmarkJson(["1", "2"], "2026-07-27T10:00:00+09:00");
    expect(parseBookmarkFile(json, "backup.json")).toEqual(["1", "2"]);
    expect(parseBookmarkFile(bookmarkCsv(["1", "2"]), "backup.csv")).toEqual(["1", "2"]);
    expect(parseBookmarkFile('{"version":2,"bookmarks":[1]}', "backup.json")).toEqual([]);
  });

  it("creates a device-neutral calendar file without a Google-specific URL", () => {
    const item = {
      id: "job-1",
      company: { id: 1, name: "Example" },
      event_name: "Internship",
      deadline: "2026-08-01",
      event_start_date: null,
      event_end_date: null,
      entry_url: null,
    } as Opportunity;
    const calendar = calendarDetails(item, "https://example.com/opportunities/job-1");
    expect(calendar?.ics).toContain("DTSTART;VALUE=DATE:20260801");
    expect(calendar?.ics).toContain("SUMMARY:Example Internship 応募締切");
    expect(calendar).not.toHaveProperty("googleUrl");
  });
});
