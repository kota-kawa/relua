// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Opportunity } from "@/lib/types";

const { loadOpportunities } = vi.hoisted(() => ({ loadOpportunities: vi.fn() }));

vi.mock("@/lib/browser-api", () => ({ loadOpportunities }));
vi.mock("@/components/bookmark-button", () => ({ notifyLocalDataChanged: vi.fn() }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={String(href)} {...props}>{children}</a>,
}));

import { ImportBookmarks } from "./import-bookmarks";

function opportunity(id: string, company: string, eventName: string) {
  return { id, company: { id: 1, name: company }, event_name: eventName } as Opportunity;
}

describe("ImportBookmarks", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState({}, "", "/import#b=existing,new,missing");
    loadOpportunities.mockReset();
  });

  afterEach(() => cleanup());

  it("shows the actual new, duplicate and unavailable counts before merging", async () => {
    window.localStorage.setItem("relua.bookmarks.v1", JSON.stringify(["existing"]));
    loadOpportunities.mockResolvedValue({
      items: [opportunity("existing", "保存済み社", "既存募集"), opportunity("new", "新規社", "新しい募集")],
      missingIds: ["missing"],
      failedIds: [],
    });

    render(<ImportBookmarks />);

    expect(await screen.findByRole("heading", { name: "1件を追加できます" })).toBeTruthy();
    expect(screen.getByText("新しい募集")).toBeTruthy();
    expect(screen.getByText("保存済み").nextElementSibling?.textContent).toBe("1件");
    expect(screen.getByText("終了・削除済み").nextElementSibling?.textContent).toBe("1件");

    fireEvent.click(screen.getByRole("button", { name: "1件を追加" }));
    expect(await screen.findByRole("heading", { name: "1件を追加しました" })).toBeTruthy();
    expect(JSON.parse(window.localStorage.getItem("relua.bookmarks.v1") ?? "[]")).toEqual(["existing", "new"]);
  });

  it("offers a retry when every opportunity lookup fails", async () => {
    window.history.replaceState({}, "", "/import#b=new");
    loadOpportunities
      .mockResolvedValueOnce({ items: [], missingIds: [], failedIds: ["new"] })
      .mockResolvedValueOnce({ items: [opportunity("new", "再試行社", "確認できた募集")], missingIds: [], failedIds: [] });

    render(<ImportBookmarks />);

    expect(await screen.findByRole("heading", { name: "保存データを確認できませんでした" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "再読み込み" }));
    expect(await screen.findByRole("heading", { name: "1件を追加できます" })).toBeTruthy();
  });

  it("explains when browser storage rejects the import", async () => {
    window.history.replaceState({}, "", "/import#b=new");
    loadOpportunities.mockResolvedValue({ items: [opportunity("new", "保存不可社", "保存する募集")], missingIds: [], failedIds: [] });
    render(<ImportBookmarks />);
    await screen.findByRole("heading", { name: "1件を追加できます" });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("denied"); });

    fireEvent.click(screen.getByRole("button", { name: "1件を追加" }));
    expect(await screen.findByRole("heading", { name: "この端末に保存できませんでした" })).toBeTruthy();
    setItem.mockRestore();
  });
});
