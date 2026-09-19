import type { Opportunity } from "@/lib/types";

export const BOOKMARKS_KEY = "relua.bookmarks.v1";
export const RECENTS_KEY = "relua.recents.v1";
export const LOCAL_DATA_EVENT = "relua:local-data-changed";
export const MAX_RECENTS = 30;
/** Keep generated links inside the range reliably handled by share sheets and scanners. */
export const MAX_TRANSFER_URL_LENGTH = 2_000;
export const MAX_QR_URL_LENGTH = 1_800;

/**
 * Links carry the server's short public code rather than the 36-character UUID.
 * At 8 fixed-width characters with no separator, a 2,000 byte link holds a few hundred
 * bookmarks instead of roughly fifty.
 */
export const PUBLIC_CODE_LENGTH = 8;
export const TRANSFER_CODE_KEY = "c";
export const TRANSFER_LEGACY_KEY = "b";
export const SHARE_CODE_KEY = "l";
export const SHARE_LEGACY_KEY = "jobs";

export type RecentEntry = { id: string; viewedAt: string };
/** Display-only details captured with a bookmark backup. IDs remain authoritative on restore. */
export type BookmarkBackupSnapshot = { id: string; company: { name: string }; event_name: string };
export type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;
export type TransferLinkError = "empty" | "invalid" | "wrong-origin" | "wrong-path" | "too-long" | "no-data" | "damaged";
export type TransferLinkValidation =
  | { ok: true; href: string; refs: string[] }
  | { ok: false; error: TransferLinkError };

const ID_PATTERN = /^[A-Za-z0-9_-]{1,100}$/;
/** Crockford base32, matching PUBLIC_CODE_ALPHABET on the server. */
const CODE_PATTERN = /^[0-9ABCDEFGHJKMNPQRSTVWXYZ]{8}$/;

export function normalizeIds(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const unique = new Set<string>();
  value.forEach((entry) => {
    const id = typeof entry === "number" && Number.isSafeInteger(entry) ? String(entry) : typeof entry === "string" ? entry.trim() : "";
    if (ID_PATTERN.test(id)) unique.add(id);
  });
  return [...unique];
}

export function normalizeCodes(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const unique = new Set<string>();
  value.forEach((entry) => {
    const code = typeof entry === "string" ? entry.trim().toUpperCase() : "";
    if (CODE_PATTERN.test(code)) unique.add(code);
  });
  return [...unique];
}

function parseJson(value: string | null): unknown {
  if (!value) return null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function getStoredValue(storage: StorageLike, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

export function readBookmarks(storage: StorageLike): string[] {
  return normalizeIds(parseJson(getStoredValue(storage, BOOKMARKS_KEY)));
}

/**
 * Single-entry memo for the raw bookmark snapshot string.
 *
 * Every card on a page reads the same localStorage snapshot through
 * useSyncExternalStore, so one bookmark toggle re-renders all of them with a
 * string that is byte-for-byte identical. Parsing per component turned a single
 * toggle into dozens of JSON.parse calls plus a Set per call inside
 * normalizeIds. The snapshot is a client-only value and the cache holds exactly
 * one entry, so there is nothing to leak between renders or requests: a server
 * render only ever sees the "[]" fallback.
 */
let snapshotCache: { raw: string; ids: string[]; idSet: Set<string> } | null = null;

function readSnapshot(raw: string) {
  if (snapshotCache?.raw === raw) return snapshotCache;
  let ids: string[];
  try {
    ids = normalizeIds(JSON.parse(raw));
  } catch {
    ids = [];
  }
  snapshotCache = { raw, ids, idSet: new Set(ids) };
  return snapshotCache;
}

/** Parses a bookmark snapshot string, returning the same array for the same input. */
export function idsFromSnapshot(raw: string): string[] {
  return readSnapshot(raw).ids;
}

/** Membership test against a bookmark snapshot, without an O(n) scan per card. */
export function snapshotHasId(raw: string, id: string): boolean {
  return readSnapshot(raw).idSet.has(id);
}

export function writeBookmarks(storage: StorageLike, ids: string[]): string[] {
  const normalized = normalizeIds(ids);
  storage.setItem(BOOKMARKS_KEY, JSON.stringify(normalized));
  return normalized;
}

export function mergeBookmarks(storage: StorageLike, ids: string[]): string[] {
  return writeBookmarks(storage, [...readBookmarks(storage), ...ids]);
}

export function newBookmarkIds(importedIds: string[], existingIds: string[]): string[] {
  const existing = new Set(normalizeIds(existingIds));
  return normalizeIds(importedIds).filter((id) => !existing.has(id));
}

export function toggleBookmark(storage: StorageLike, id: string): { ids: string[]; saved: boolean } {
  const current = readBookmarks(storage);
  const saved = !current.includes(id);
  const ids = writeBookmarks(storage, saved ? [...current, id] : current.filter((entry) => entry !== id));
  return { ids, saved };
}

export function removeBookmarks(storage: StorageLike, ids: string[]): string[] {
  const removed = new Set(normalizeIds(ids));
  return writeBookmarks(storage, readBookmarks(storage).filter((id) => !removed.has(id)));
}

export function readRecents(storage: StorageLike): RecentEntry[] {
  const value = parseJson(getStoredValue(storage, RECENTS_KEY));
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  return value.flatMap((entry): RecentEntry[] => {
    if (!entry || typeof entry !== "object") return [];
    const id = normalizeIds([(entry as RecentEntry).id])[0];
    const viewedAt = (entry as RecentEntry).viewedAt;
    if (!id || seen.has(id) || typeof viewedAt !== "string" || Number.isNaN(Date.parse(viewedAt))) return [];
    seen.add(id);
    return [{ id, viewedAt }];
  }).slice(0, MAX_RECENTS);
}

export function recordRecent(storage: StorageLike, id: string, viewedAt = new Date().toISOString()): RecentEntry[] {
  const normalized = normalizeIds([id])[0];
  if (!normalized) return readRecents(storage);
  const next = [{ id: normalized, viewedAt }, ...readRecents(storage).filter((entry) => entry.id !== normalized)].slice(0, MAX_RECENTS);
  storage.setItem(RECENTS_KEY, JSON.stringify(next));
  return next;
}

export function clearRecents(storage: StorageLike) {
  storage.removeItem(RECENTS_KEY);
}

export function parseFragmentIds(hash: string, key: "b" | "jobs"): string[] {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const raw = params.get(key);
  if (!raw) return [];
  return normalizeIds(raw.split(","));
}

export function buildFragmentUrl(origin: string, path: "/import" | "/list", key: "b" | "jobs", ids: string[]): string {
  const url = new URL(path, origin);
  const value = normalizeIds(ids).map(encodeURIComponent).join(",");
  url.hash = `${key}=${value}`;
  return url.toString();
}

/**
 * Codes are fixed width, so they need no separator between entries.
 *
 * Because there is no separator there is also no redundancy: a link that a
 * messaging app wrapped or trimmed still parses, it just yields fewer codes.
 * `complete` reports whether the payload is exactly a whole number of valid
 * codes, so callers that can still warn the user do not import a partial list
 * and call it a success.
 */
export function readFragmentCodes(hash: string, key: "c" | "l"): { codes: string[]; complete: boolean } {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const raw = params.get(key)?.toUpperCase() ?? "";
  if (!raw) return { codes: [], complete: true };
  const chunks = raw.match(new RegExp(`.{1,${PUBLIC_CODE_LENGTH}}`, "g")) ?? [];
  return { codes: normalizeCodes(chunks), complete: chunks.every((chunk) => CODE_PATTERN.test(chunk)) };
}

export function parseFragmentCodes(hash: string, key: "c" | "l"): string[] {
  return readFragmentCodes(hash, key).codes;
}

export function buildCodeFragmentUrl(origin: string, path: "/import" | "/list", key: "c" | "l", codes: string[]): string {
  const url = new URL(path, origin);
  url.hash = `${key}=${normalizeCodes(codes).join("")}`;
  return url.toString();
}

export function urlFitsTransferLimit(url: string, limit = MAX_TRANSFER_URL_LENGTH): boolean {
  return new TextEncoder().encode(url).length <= limit;
}

export function validateTransferLink(value: string, expectedOrigin: string): TransferLinkValidation {
  const trimmed = value.trim();
  if (!trimmed) return { ok: false, error: "empty" };
  if (!urlFitsTransferLimit(trimmed)) return { ok: false, error: "too-long" };

  let expected: URL;
  let candidate: URL;
  try {
    expected = new URL(expectedOrigin);
    candidate = new URL(trimmed);
  } catch {
    return { ok: false, error: "invalid" };
  }

  if (candidate.origin !== expected.origin) return { ok: false, error: "wrong-origin" };
  if (candidate.pathname.replace(/\/+$/, "") !== "/import") return { ok: false, error: "wrong-path" };

  const { codes, complete } = readFragmentCodes(candidate.hash, TRANSFER_CODE_KEY);
  /* Importing whatever survived a cut-off link and reporting success would hide
     the loss on both devices, so a damaged payload is refused outright. */
  if (!complete) return { ok: false, error: "damaged" };
  if (codes.length) {
    const canonical = new URL(buildCodeFragmentUrl(expected.origin, "/import", TRANSFER_CODE_KEY, codes));
    return { ok: true, href: `${canonical.pathname}${canonical.hash}`, refs: codes };
  }

  /* Links minted before public codes existed still carry UUIDs. */
  const ids = parseFragmentIds(candidate.hash, TRANSFER_LEGACY_KEY);
  if (!ids.length) return { ok: false, error: "no-data" };

  const canonical = new URL(buildFragmentUrl(expected.origin, "/import", TRANSFER_LEGACY_KEY, ids));
  return { ok: true, href: `${canonical.pathname}${canonical.hash}`, refs: ids };
}

export function bookmarkJson(ids: string[], snapshots: readonly BookmarkBackupSnapshot[] = [], exportedAt = new Date().toISOString()): string {
  const snapshotsById = new Map(snapshots.map((item) => [item.id, item]));
  const bookmarks = normalizeIds(ids).map((id) => {
    const snapshot = snapshotsById.get(id);
    if (!snapshot || !snapshot.company?.name || !snapshot.event_name) return { id };
    return { id, company_name: snapshot.company.name, title: snapshot.event_name };
  });
  return JSON.stringify({ version: 2, bookmarks, exported_at: exportedAt }, null, 2);
}

export function bookmarkCsv(ids: string[]): string {
  return ["id", ...normalizeIds(ids)].join("\n") + "\n";
}

export function parseBookmarkFile(content: string, fileName: string): string[] {
  if (fileName.toLowerCase().endsWith(".json")) {
    const parsed = parseJson(content);
    if (!parsed || typeof parsed !== "object") return [];
    const backup = parsed as { version?: unknown; bookmarks?: unknown };
    if (backup.version === 1) return normalizeIds(backup.bookmarks);
    if (backup.version !== 2 || !Array.isArray(backup.bookmarks)) return [];
    return normalizeIds(backup.bookmarks.map((entry) => (
      entry && typeof entry === "object" ? (entry as { id?: unknown }).id : undefined
    )));
  }
  if (fileName.toLowerCase().endsWith(".csv")) {
    const lines = content.replace(/^\uFEFF/, "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (lines[0]?.toLowerCase() !== "id") return [];
    return normalizeIds(lines.slice(1).map((line) => line.split(",")[0]?.replace(/^"|"$/g, "")));
  }
  return [];
}

function icsEscape(value: string) {
  return value.replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/,/g, "\\,").replace(/;/g, "\\;");
}

function compactDate(value: string) {
  return value.replaceAll("-", "");
}

function nextDate(value: string) {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

export function calendarDetails(item: Opportunity, detailUrl: string) {
  const start = item.event_start_date ?? item.deadline;
  if (!start) return null;
  const isEvent = Boolean(item.event_start_date);
  const end = isEvent ? nextDate(item.event_end_date ?? start) : nextDate(start);
  const title = isEvent ? `${item.company.name} ${item.event_name}` : `${item.company.name} ${item.event_name} 応募締切`;
  const description = [
    item.deadline ? `応募締切: ${item.deadline}` : null,
    `募集詳細: ${detailUrl}`,
    item.entry_url ? `公式応募ページ: ${item.entry_url}` : null,
  ].filter(Boolean).join("\n");
  const uid = `${item.id}@relua.local`;
  const ics = [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//relua//Local Calendar//JA", "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT", `UID:${uid}`, `DTSTAMP:${new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "")}`,
    `DTSTART;VALUE=DATE:${compactDate(start)}`, `DTEND;VALUE=DATE:${compactDate(end)}`,
    `SUMMARY:${icsEscape(title)}`, `DESCRIPTION:${icsEscape(description)}`, `URL:${icsEscape(detailUrl)}`,
    "END:VEVENT", "END:VCALENDAR", "",
  ].join("\r\n");
  return { ics, title };
}
