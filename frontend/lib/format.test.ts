import { describe, expect, it } from "vitest";

import { filterHref } from "./format";

describe("filterHref", () => {
  it("preserves selected filters and resets pagination", () => {
    expect(filterHref([
      ["q", "エンジニア"],
      ["status", "status-02"],
      ["status", "status-04"],
      ["page", "3"],
      ["view", "list"],
    ])).toBe("/?q=%E3%82%A8%E3%83%B3%E3%82%B8%E3%83%8B%E3%82%A2&status=status-02&status=status-04&view=list#listings");
  });

  it("returns the listing anchor when every filter is removed", () => {
    expect(filterHref([["page", "2"]])).toBe("/#listings");
  });
});
