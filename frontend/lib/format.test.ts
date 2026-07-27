import { describe, expect, it, vi } from "vitest";

import { deadlineCompactLabel, filterHref } from "./format";

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

describe("deadlineCompactLabel", () => {
  it("drops the year from a distant deadline so it fits the sticky bar", () => {
    vi.setSystemTime(new Date("2026-07-27T09:00:00+09:00"));
    expect(deadlineCompactLabel("2026-08-07")).toBe("8月7日(金)");
    vi.useRealTimers();
  });

  it("keeps the relative phrase when the deadline is near", () => {
    vi.setSystemTime(new Date("2026-07-27T09:00:00+09:00"));
    /* The deadline runs to the end of the 29th, so the 29th itself counts. */
    expect(deadlineCompactLabel("2026-07-29")).toBe("あと3日");
    expect(deadlineCompactLabel(null)).toBe("締切未定");
    vi.useRealTimers();
  });
});
