import { describe, expect, it } from "vitest";

import { STAGGER_LIMIT, stagger } from "./motion";

describe("the entrance cascade", () => {
  it("gives each of the first items its own step", () => {
    expect(stagger(0)).toEqual({ "--stagger": 0 });
    expect(stagger(3)).toEqual({ "--stagger": 3 });
  });

  it("holds the delay flat past the limit so long lists still arrive at once", () => {
    // 60 calendar rows at one step each would land nearly two seconds apart.
    expect(stagger(STAGGER_LIMIT + 1)).toEqual({ "--stagger": STAGGER_LIMIT });
    expect(stagger(59)).toEqual({ "--stagger": STAGGER_LIMIT });
  });
});
