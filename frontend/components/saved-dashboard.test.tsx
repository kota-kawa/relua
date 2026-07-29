// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { loadOpportunities } = vi.hoisted(() => ({ loadOpportunities: vi.fn() }));
const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const originalShare = Object.getOwnPropertyDescriptor(navigator, "share");

vi.mock("@/lib/browser-api", () => ({ loadOpportunities }));
vi.mock("@/components/bookmark-button", () => ({ notifyLocalDataChanged: vi.fn() }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={String(href)} {...props}>{children}</a>,
}));

import { SavedDashboard } from "./saved-dashboard";

describe("SavedDashboard", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("relua.bookmarks.v1", JSON.stringify(["job-1"]));
    loadOpportunities.mockResolvedValue({ items: [], missingIds: [], failedIds: [] });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    if (originalClipboard) Object.defineProperty(navigator, "clipboard", originalClipboard);
    else delete (navigator as Navigator & Record<string, unknown>).clipboard;
    if (originalShare) Object.defineProperty(navigator, "share", originalShare);
    else delete (navigator as Navigator & Record<string, unknown>).share;
  });

  it("copies the transfer link directly without opening the native share dialog", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const share = vi.fn();
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    Object.defineProperty(navigator, "share", { configurable: true, value: share });

    render(<SavedDashboard />);
    fireEvent.click(await screen.findByRole("button", { name: "引き継ぎリンクをコピー" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/import#b=job-1`));
    expect(share).not.toHaveBeenCalled();
  });
});
