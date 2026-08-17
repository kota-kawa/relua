import { describe, expect, it } from "vitest";

import { getListingSeo, listingMetadata, type SeoFacetCatalog } from "./seo";

const catalog: SeoFacetCatalog = {
  industry: new Map([["industry-01", "IT・通信"]]),
  event_type: new Map([["type-01", "インターン"]]),
  graduation_year: new Map([["grad-02", "27卒"]]),
};

describe("getListingSeo", () => {
  it("keeps the clean default listing indexable", () => {
    expect(getListingSeo({})).toEqual({ index: true, follow: true, canonical: "/" });
  });

  it("canonicalizes presentation-only views to the clean listing", () => {
    expect(getListingSeo({ status: "status-02", view: "list" }))
      .toEqual({ index: true, follow: true, canonical: "/" });
    expect(getListingSeo({ view: "calendar" }))
      .toEqual({ index: true, follow: true, canonical: "/" });
  });

  it("keeps pure pagination pages indexable with self-canonical URLs", () => {
    expect(getListingSeo({ page: "2" }))
      .toEqual({ index: true, follow: true, canonical: "/?page=2" });
    expect(getListingSeo({ status: "status-02", page: "3" }))
      .toEqual({ index: true, follow: true, canonical: "/?page=3" });
  });

  it("indexes high-intent single-category pages with self-canonical URLs", () => {
    expect(getListingSeo({ industry: "industry-01" }, { catalog, resultTotal: 10 }))
      .toEqual({
        index: true,
        follow: true,
        canonical: "/?industry=industry-01",
        facet: { key: "industry", slug: "industry-01", label: "IT・通信" },
      });
    expect(getListingSeo({ event_type: "type-01", page: "2" }, { catalog, resultTotal: 10 }))
      .toEqual({
        index: true,
        follow: true,
        canonical: "/?event_type=type-01&page=2",
        facet: { key: "event_type", slug: "type-01", label: "インターン" },
      });
  });

  it("noindexes thin and arbitrary category URLs", () => {
    expect(getListingSeo({ industry: "industry-01" }, { catalog, resultTotal: 4 }))
      .toEqual({ index: false, follow: true });
    expect(getListingSeo({ industry: "industry-01", event_type: "type-01" }, { catalog, resultTotal: 10 }))
      .toEqual({ index: false, follow: true });
    expect(getListingSeo({ sector: "sector-1-01" }, { catalog, resultTotal: 10 }))
      .toEqual({ index: false, follow: true });
  });

  it("noindexes search and sorting URLs", () => {
    expect(getListingSeo({ q: "エンジニア" })).toEqual({ index: false, follow: true });
    expect(getListingSeo({ sort: "updated" })).toEqual({ index: false, follow: true });
    expect(getListingSeo({ industry: "industry-01", sort: "updated" }, { catalog, resultTotal: 10 }))
      .toEqual({ index: false, follow: true });
  });

  it("does not canonicalize later list or calendar pages to the wrong page size", () => {
    expect(getListingSeo({ view: "list", page: "2" })).toEqual({ index: false, follow: true });
    expect(getListingSeo({ view: "calendar", page: "2" })).toEqual({ index: false, follow: true });
  });

  it("returns page metadata compatible with Next metadata merging", () => {
    expect(listingMetadata({ sort: "updated" })).toEqual({
      alternates: undefined,
      robots: { index: false, follow: true },
    });
    expect(listingMetadata({ page: "2" })).toEqual({
      alternates: { canonical: "/?page=2" },
      robots: { index: true, follow: true },
    });
    expect(listingMetadata({ industry: "industry-01" }, { catalog, resultTotal: 10 })).toEqual({
      title: "IT・通信のインターン・本選考情報",
      description: "IT・通信のインターン・本選考・イベントの募集情報を検索できます。締切や応募条件を確認して、公式サイトから応募できます。",
      openGraph: {
        title: "IT・通信のインターン・本選考情報",
        description: "IT・通信のインターン・本選考・イベントの募集情報を検索できます。締切や応募条件を確認して、公式サイトから応募できます。",
      },
      twitter: {
        title: "IT・通信のインターン・本選考情報",
        description: "IT・通信のインターン・本選考・イベントの募集情報を検索できます。締切や応募条件を確認して、公式サイトから応募できます。",
      },
      alternates: { canonical: "/?industry=industry-01" },
      robots: { index: true, follow: true },
    });
  });
});
