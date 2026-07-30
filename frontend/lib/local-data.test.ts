import { describe, expect, it } from "vitest";

import {
  bookmarkCsv,
  bookmarkJson,
  buildCodeFragmentUrl,
  buildFragmentUrl,
  calendarDetails,
  mergeBookmarks,
  newBookmarkIds,
  normalizeIds,
  parseBookmarkFile,
  parseFragmentCodes,
  parseFragmentIds,
  readBookmarks,
  recordRecent,
  removeBookmarks,
  toggleBookmark,
  urlFitsTransferLimit,
  validateTransferLink,
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

  it("round-trips fixed-width public codes without separators", () => {
    const url = buildCodeFragmentUrl("https://example.com/current", "/import", "c", ["A1B2C3D4", "e5f6g7h8"]);
    expect(url).toBe("https://example.com/import#c=A1B2C3D4E5F6G7H8");
    expect(parseFragmentCodes(new URL(url).hash, "c")).toEqual(["A1B2C3D4", "E5F6G7H8"]);
  });

  it("drops codes that are truncated or use excluded letters", () => {
    expect(parseFragmentCodes("#c=A1B2C3D4XYZ", "c")).toEqual(["A1B2C3D4"]);
    expect(parseFragmentCodes("#c=IIIIIIII", "c")).toEqual([]);
  });

  it("measures transfer limits in encoded bytes", () => {
    expect(urlFitsTransferLimit("a", 1)).toBe(true);
    expect(urlFitsTransferLimit("あ", 1)).toBe(false);
    const uuidIds = Array.from({ length: 55 }, (_, index) => `${String(index).padStart(8, "0")}-aaaa-4aaa-8aaa-${String(index).padStart(12, "0")}`);
    expect(urlFitsTransferLimit(buildFragmentUrl("https://example.com", "/import", "b", uuidIds))).toBe(false);
  });

  it("fits several hundred public codes in one transfer link", () => {
    const codes = Array.from({ length: 240 }, (_, index) => `A${String(index).padStart(7, "0")}`);
    expect(urlFitsTransferLimit(buildCodeFragmentUrl("https://example.com", "/import", "c", codes))).toBe(true);
  });

  it("accepts only same-origin import links with bookmark data", () => {
    const valid = validateTransferLink(" https://example.com/import#c=A1B2C3D4A1B2C3D4 ", "https://example.com");
    expect(valid).toEqual({ ok: true, href: "/import#c=A1B2C3D4", refs: ["A1B2C3D4"] });
    expect(validateTransferLink("https://evil.example/import#c=A1B2C3D4", "https://example.com")).toEqual({ ok: false, error: "wrong-origin" });
    expect(validateTransferLink("https://example.com/list#c=A1B2C3D4", "https://example.com")).toEqual({ ok: false, error: "wrong-path" });
    expect(validateTransferLink("https://example.com/import", "https://example.com")).toEqual({ ok: false, error: "no-data" });
    expect(validateTransferLink("not a URL", "https://example.com")).toEqual({ ok: false, error: "invalid" });
  });

  it("still accepts UUID links minted before public codes existed", () => {
    expect(validateTransferLink("https://example.com/import#b=1,2,2", "https://example.com")).toEqual({
      ok: true,
      href: "/import#b=1,2",
      refs: ["1", "2"],
    });
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
