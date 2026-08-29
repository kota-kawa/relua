import { afterEach, describe, expect, it } from "vitest";

import { beginNavigation, isNavigationPending, resetNavigationProgress } from "./navigation-progress";

afterEach(() => resetNavigationProgress());

describe("the navigation count", () => {
  it("stays raised until the last of several overlapping navigations ends", () => {
    // A filter change and a link click can be in flight at the same time; the
    // indicator has to survive the first of them finishing.
    const endFilter = beginNavigation();
    const endLink = beginNavigation();
    expect(isNavigationPending()).toBe(true);

    endFilter();
    expect(isNavigationPending()).toBe(true);

    endLink();
    expect(isNavigationPending()).toBe(false);
  });

  it("ignores an end that is reported twice", () => {
    // React can run an effect cleanup and a later unmount over the same close.
    const end = beginNavigation();
    const other = beginNavigation();
    end();
    end();

    expect(isNavigationPending()).toBe(true);
    other();
    expect(isNavigationPending()).toBe(false);
  });
});
