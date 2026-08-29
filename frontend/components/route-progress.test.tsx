// @vitest-environment jsdom

import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { beginNavigation, resetNavigationProgress } from "@/lib/navigation-progress";

import { RouteProgress } from "./route-progress";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  resetNavigationProgress();
  vi.useRealTimers();
});

const bar = () => document.querySelector(".route-progress");

describe("the navigation progress bar", () => {
  it("stays away for a navigation that finishes quickly", () => {
    render(<RouteProgress />);
    let end = () => {};

    act(() => { end = beginNavigation(); });
    act(() => void vi.advanceTimersByTime(100));
    expect(bar()).toBeNull();

    // Most listing navigations land inside this window; a bar that appeared and
    // vanished again inside 200ms would read as a glitch, not as progress.
    act(() => end());
    act(() => void vi.advanceTimersByTime(1000));
    expect(bar()).toBeNull();
  });

  it("runs, completes and clears for a navigation that takes a while", () => {
    render(<RouteProgress />);
    let end = () => {};

    act(() => { end = beginNavigation(); });
    act(() => void vi.advanceTimersByTime(200));
    expect(bar()?.getAttribute("data-phase")).toBe("loading");

    act(() => end());
    expect(bar()?.getAttribute("data-phase")).toBe("done");

    act(() => void vi.advanceTimersByTime(400));
    expect(bar()).toBeNull();
  });
});
