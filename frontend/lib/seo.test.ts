import { describe, expect, it } from "vitest";

import { getListingSeo, listingMetadata } from "./seo";

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

  it("noindexes search, filter, and sorting URLs", () => {
    expect(getListingSeo({ q: "エンジニア" })).toEqual({ index: false, follow: true });
    expect(getListingSeo({ industry: "industry-01" })).toEqual({ index: false, follow: true });
    expect(getListingSeo({ sort: "updated" })).toEqual({ index: false, follow: true });
    expect(getListingSeo({ industry: "industry-01", page: "2" }))
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
  });
});
