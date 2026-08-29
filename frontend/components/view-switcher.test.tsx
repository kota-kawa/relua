// @vitest-environment jsdom

import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { beginNavigation, resetNavigationProgress } from "@/lib/navigation-progress";

/* The real Link keeps the navigation client-side; the stand-in has to swallow
   it too, or jsdom tries to leave the document on every click. */
vi.mock("next/link", () => ({
  default: ({ href, children, onClick, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={String(href)} onClick={(event) => { event.preventDefault(); onClick?.(event); }} {...props}>{children}</a>
  ),
  useLinkStatus: () => ({ pending: false }),
}));

import { ViewSwitcher } from "./view-switcher";

afterEach(() => {
  cleanup();
  resetNavigationProgress();
});

function indexOf(container: HTMLElement) {
  return container.querySelector<HTMLElement>(".view-switcher")?.style.getPropertyValue("--view-index");
}

describe("the sliding view highlight", () => {
  it("moves to the pressed view while its navigation is in flight", () => {
    const { container, getByTitle } = render(<ViewSwitcher params={{}} view="cards" />);
    expect(indexOf(container)).toBe("0");

    fireEvent.click(getByTitle("締切順表示"));
    act(() => void beginNavigation());

    expect(indexOf(container)).toBe("2");
    /* The page is still the card view, and that is what `aria-current` reports:
       the highlight is an answer to the press, not a claim about the page. */
    expect(getByTitle("カード表示").getAttribute("aria-current")).toBe("page");
    expect(getByTitle("締切順表示").getAttribute("aria-current")).toBeNull();
  });

  it("returns to the open view when the navigation ends without one", () => {
    const { container, getByTitle } = render(<ViewSwitcher params={{}} view="cards" />);

    fireEvent.click(getByTitle("一覧表示"));
    let end = () => {};
    act(() => { end = beginNavigation(); });
    expect(indexOf(container)).toBe("1");

    // Cancelled — the URL never changed, so the highlight must not stay ahead.
    act(() => end());
    expect(indexOf(container)).toBe("0");
  });

  it("carries the current filters into every view link", () => {
    const { getByTitle } = render(<ViewSwitcher params={{ industry: "industry-01", page: "3" }} view="cards" />);

    expect(getByTitle("一覧表示").getAttribute("href")).toBe("/?industry=industry-01&view=list#listings");
    // Paging does not survive a view change: the pages are a different size.
    expect(getByTitle("カード表示").getAttribute("href")).toBe("/?industry=industry-01#listings");
  });
});
