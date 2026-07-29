// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TransferLinkForm } from "./transfer-link-form";

describe("TransferLinkForm", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("validates a pasted same-origin link before opening confirmation", () => {
    const onSubmit = vi.fn();
    render(<TransferLinkForm onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("引き継ぎリンク"), { target: { value: `${window.location.origin}/import#b=1,2,2` } });
    fireEvent.click(screen.getByRole("button", { name: "内容を確認" }));
    expect(onSubmit).toHaveBeenCalledWith("/import#b=1,2");
  });

  it("rejects a link from another origin", () => {
    render(<TransferLinkForm onSubmit={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("引き継ぎリンク"), { target: { value: "https://evil.example/import#b=1" } });
    fireEvent.click(screen.getByRole("button", { name: "内容を確認" }));
    expect(screen.getByRole("alert").textContent).toContain("このサービスで作成された");
  });

  it("can read a link from the clipboard without importing immediately", async () => {
    const readText = vi.fn().mockResolvedValue(`${window.location.origin}/import#b=job-1`);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { readText } });
    const onSubmit = vi.fn();
    render(<TransferLinkForm onSubmit={onSubmit} />);

    fireEvent.click(screen.getByRole("button", { name: "クリップボードから貼り付け" }));
    await waitFor(() => expect((screen.getByLabelText("引き継ぎリンク") as HTMLTextAreaElement).value).toContain("job-1"));
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "内容を確認" }));
    expect(onSubmit).toHaveBeenCalledWith("/import#b=job-1");
  });

  it("falls back to manual paste when clipboard access is denied", async () => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { readText: vi.fn().mockRejectedValue(new DOMException("denied")) } });
    render(<TransferLinkForm onSubmit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "クリップボードから貼り付け" }));
    expect((await screen.findByRole("alert")).textContent).toContain("手動で貼り付けてください");
  });
});
