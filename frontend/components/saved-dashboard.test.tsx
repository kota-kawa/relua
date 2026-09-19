// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { loadOpportunities } = vi.hoisted(() => ({ loadOpportunities: vi.fn() }));
const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const originalShare = Object.getOwnPropertyDescriptor(navigator, "share");

vi.mock("@/lib/browser-api", () => ({ loadOpportunities }));
vi.mock("@/components/bookmark-button", () => ({
  notifyLocalDataChanged: vi.fn(),
  BookmarkButton: () => <button type="button">保存</button>,
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={String(href)} {...props}>{children}</a>,
  useLinkStatus: () => ({ pending: false }),
}));

import { SavedDashboard } from "./saved-dashboard";
import type { Opportunity } from "@/lib/types";

const master = { id: 1, slug: "value-01", name: "値" };
const savedItem = {
  id: "job-1",
  public_code: "A1B2C3D4",
  url: "http://localhost:3100/opportunities/A1B2C3D4",
  recruitment_status: master,
  company: { id: 1, name: "株式会社テスト", public_code: "CMPNY001", url: "https://relua.example/companies/CMPNY001" },
  industry: master,
  sector: master,
  event_name: "テストインターン",
  deadline: "2026-09-01",
  event_type: master,
  description: "説明",
  event_format: master,
  location: null,
  selection_process: null,
  homepage_url: null,
  job_categories: [master],
  tags: [],
  event_start_date: null,
  event_end_date: null,
  period_note: null,
  requirements: null,
  compensation: null,
  graduation_years: [master],
  degrees: [master],
  audience_note: null,
  recruitment_start_date: null,
  entry_url: null,
  source_url: "https://example.com/source",
  created_at: "2026-07-01T00:00:00Z",
  updated_at: "2026-07-01T00:00:00Z",
  source_checked_at: "2026-07-01T00:00:00Z",
} satisfies Opportunity;

describe("SavedDashboard", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("relua.bookmarks.v1", JSON.stringify(["job-1"]));
    loadOpportunities.mockResolvedValue({ items: [savedItem], missingIds: [], failedIds: [] });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    /* `Navigator` declares clipboard/share as required (non-optional, read-only)
       properties, so `delete` on that type is a compile error under either
       spelling. Casting through `unknown` to a plain index-signature type
       satisfies `delete` without touching runtime behavior. */
    const nav = navigator as unknown as Record<string, unknown>;
    if (originalClipboard) Object.defineProperty(navigator, "clipboard", originalClipboard);
    else delete nav.clipboard;
    if (originalShare) Object.defineProperty(navigator, "share", originalShare);
    else delete nav.share;
  });

  it("copies the transfer link directly without opening the native share dialog", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const share = vi.fn();
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    Object.defineProperty(navigator, "share", { configurable: true, value: share });

    render(<SavedDashboard />);
    const copyButton = await screen.findByRole("button", { name: "引き継ぎリンクをコピー" }) as HTMLButtonElement;
    await waitFor(() => expect(copyButton.disabled).toBe(false));
    fireEvent.click(copyButton);

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/import#c=A1B2C3D4`));
    expect(share).not.toHaveBeenCalled();
  });

  it("revalidates a cached entry once it is older than the cache TTL", async () => {
    /* Fetching only the ids that changed is what keeps one bookmark toggle from
       refetching the whole list, but an entry kept forever would mean a closed
       opening keeps rendering: `loadOne` fetches `no-store` precisely because a
       saved entry can be withdrawn while this page is open, and a stale hit
       never reaches `missingIds`, so it is never dropped from localStorage or
       left out of a transfer link. */
    const fetchedIds = (): string[][] => loadOpportunities.mock.calls.map((call) => call[0] as string[]);

    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<SavedDashboard />);
      await waitFor(() => expect(fetchedIds()).toContainEqual(["job-1"]));
      loadOpportunities.mockClear();

      // A second bookmark arriving inside the TTL only costs a fetch for that id.
      loadOpportunities.mockResolvedValue({ items: [], missingIds: [], failedIds: [] });
      window.localStorage.setItem("relua.bookmarks.v1", JSON.stringify(["job-1", "job-2"]));
      window.dispatchEvent(new Event("relua:local-data-changed"));
      await waitFor(() => expect(fetchedIds()).toContainEqual(["job-2"]));
      expect(fetchedIds()).not.toContainEqual(["job-1", "job-2"]);
      loadOpportunities.mockClear();

      // Past the TTL the cached entry is fetched again rather than trusted.
      vi.advanceTimersByTime(6 * 60 * 1000);
      window.localStorage.setItem("relua.bookmarks.v1", JSON.stringify(["job-1"]));
      window.dispatchEvent(new Event("relua:local-data-changed"));
      await waitFor(() => expect(fetchedIds()).toContainEqual(["job-1"]));
    } finally {
      vi.useRealTimers();
    }
  });
});
