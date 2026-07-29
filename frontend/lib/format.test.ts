import { describe, expect, it, vi } from "vitest";

import {
  currentGraduationYears,
  deadlineCompactLabel,
  filterHref,
  labelledSectors,
  actionableFilterItems,
  activeFilterCount,
  hasDefaultOpenStatus,
  searchableStatuses,
  withDefaultOpenStatus,
} from "./format";

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

const cohorts = [
  { id: 1, slug: "grad-01", name: "26卒" },
  { id: 2, slug: "grad-02", name: "27卒" },
  { id: 3, slug: "grad-03", name: "28卒" },
  { id: 6, slug: "grad-06", name: "学年不問" },
];

describe("currentGraduationYears", () => {
  it("drops cohorts that already graduated", () => {
    /* July 2026: 26卒 graduated in March and is no longer job-hunting. */
    const now = new Date("2026-07-27T09:00:00+09:00");
    expect(currentGraduationYears(cohorts, [], now).map((c) => c.name))
      .toEqual(["27卒", "28卒", "学年不問"]);
  });

  it("keeps the graduating cohort until its March is over", () => {
    const now = new Date("2026-02-15T09:00:00+09:00");
    expect(currentGraduationYears(cohorts, [], now).map((c) => c.name))
      .toEqual(["26卒", "27卒", "28卒", "学年不問"]);
  });

  it("keeps a spent cohort that the URL still selects, so it can be unchecked", () => {
    const now = new Date("2026-07-27T09:00:00+09:00");
    expect(currentGraduationYears(cohorts, ["grad-01"], now).map((c) => c.name))
      .toEqual(["26卒", "27卒", "28卒", "学年不問"]);
  });

  it("reads the year in Tokyo, not the runtime's own timezone", () => {
    /* 2026-04-01 09:00 JST is still 2026-03-31 in UTC; the JST date decides. */
    const now = new Date("2026-04-01T09:00:00+09:00");
    expect(currentGraduationYears(cohorts, [], now).map((c) => c.name))
      .toEqual(["27卒", "28卒", "学年不問"]);
  });
});

describe("searchableStatuses", () => {
  const statuses = [
    { id: 2, slug: "status-02", name: "募集中" },
    { id: 5, slug: "status-05", name: "不明" },
  ];

  it("hides 不明, which nobody searches for", () => {
    expect(searchableStatuses(statuses, []).map((s) => s.name)).toEqual(["募集中"]);
  });

  it("keeps 不明 while it is selected so the filter can be cleared", () => {
    expect(searchableStatuses(statuses, ["status-05"]).map((s) => s.name)).toEqual(["募集中", "不明"]);
  });
});

describe("withDefaultOpenStatus", () => {
  it("uses 募集中 as the listing baseline unless all statuses were explicitly requested", () => {
    expect(withDefaultOpenStatus({})).toEqual({ status: "status-02" });
    expect(withDefaultOpenStatus({ status_scope: "all" })).toEqual({ status_scope: "all" });
    expect(withDefaultOpenStatus({ status: "status-01" })).toEqual({ status: "status-01" });
  });
});

describe("default open status", () => {
  it("does not count the normal 募集中 baseline as an applied filter", () => {
    const params = withDefaultOpenStatus({});
    expect(hasDefaultOpenStatus(params)).toBe(true);
    expect(activeFilterCount(params)).toBe(0);
  });

  it("counts a status selected through a shared URL", () => {
    expect(hasDefaultOpenStatus({ status: "status-01" })).toBe(false);
    expect(activeFilterCount({ status: "status-01" })).toBe(1);
  });
});

describe("actionableFilterItems", () => {
  const items = [
    { id: 1, slug: "online", name: "オンライン" },
    { id: 2, slug: "other", name: "その他" },
    { id: 3, slug: "unknown", name: "不明" },
  ];

  it("hides generic buckets but keeps a selected value removable", () => {
    expect(actionableFilterItems(items, []).map((item) => item.name)).toEqual(["オンライン"]);
    expect(actionableFilterItems(items, ["other"]).map((item) => item.name)).toEqual(["オンライン", "その他"]);
  });
});

describe("labelledSectors", () => {
  const masters = {
    industries: [
      { id: 1, slug: "industry-01", name: "IT・通信" },
      { id: 2, slug: "industry-02", name: "メーカー" },
    ],
    sectors: [
      { id: 1, slug: "sector-1-01", name: "ソフトウェア", industry_id: 1 },
      { id: 2, slug: "sector-1-06", name: "その他", industry_id: 1 },
      { id: 3, slug: "sector-2-14", name: "その他", industry_id: 2 },
    ],
  };

  it("qualifies only the duplicated labels with their parent industry", () => {
    expect(labelledSectors(masters as never).map((s) => s.name))
      .toEqual(["ソフトウェア", "その他（IT・通信）", "その他（メーカー）"]);
  });
});
