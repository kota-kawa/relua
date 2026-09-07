import { describe, expect, it } from "vitest";

import { companyIsIndexable, companyMetadata, getListingSeo, listingMetadata, opportunityMetadata, type SeoFacetCatalog } from "./seo";
import type { CompanyDetail, Opportunity } from "./types";

const catalog: SeoFacetCatalog = {
  industry: new Map([["industry-01", "IT・通信"]]),
  sector: new Map([["sector-1-01", "ソフトウェア"]]),
  job_category: new Map([["job-01", "ソフトウェアエンジニア"]]),
  event_type: new Map([["type-01", "インターン"]]),
  event_format: new Map([["format-01", "オンライン"]]),
  graduation_year: new Map([["grad-02", "27卒"]]),
};

const googleBot = (index: boolean) => ({
  index,
  follow: true,
  "max-image-preview": "large",
  "max-snippet": -1,
  "max-video-preview": -1,
});

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

  it("keeps allowlisted categories stable regardless of inventory fluctuations", () => {
    expect(getListingSeo({ industry: "industry-01" }, { catalog, resultTotal: 1 }).index).toBe(true);
    expect(getListingSeo({ industry: "industry-01" }, { catalog, resultTotal: 4 }).index).toBe(true);
    expect(getListingSeo({ industry: "industry-01" }, { catalog, resultTotal: 7 }).index).toBe(true);
    expect(getListingSeo({ industry: "industry-01", event_type: "type-01" }, { catalog, resultTotal: 10 }))
      .toEqual({ index: false, follow: true });
    expect(getListingSeo({ industry: "industry-99" }, { catalog, resultTotal: 10 }))
      .toEqual({ index: false, follow: true });
  });

  it("keeps unknown and duplicate query parameters out of the index", () => {
    expect(getListingSeo({ unknown: "value" })).toEqual({ index: false, follow: true });
    expect(getListingSeo({ industry: ["industry-01", "industry-01"] }, { catalog, resultTotal: 10 }))
      .toEqual({ index: false, follow: true });
  });

  it("indexes allowlisted sector, role, and format intents with one result", () => {
    expect(getListingSeo({ sector: "sector-1-01" }, { catalog, resultTotal: 1 }).index).toBe(true);
    expect(getListingSeo({ job_category: "job-01" }, { catalog, resultTotal: 1 }).index).toBe(true);
    expect(getListingSeo({ event_format: "format-01" }, { catalog, resultTotal: 1 }).index).toBe(true);
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

  it("noindexes pagination beyond the result set", () => {
    expect(getListingSeo({ page: "3" }, { totalPages: 2 }))
      .toEqual({ index: false, follow: true });
  });

  it("returns page metadata compatible with Next metadata merging", () => {
    expect(listingMetadata({ sort: "updated" })).toEqual({
      alternates: undefined,
      robots: { index: false, follow: true, googleBot: googleBot(false) },
    });
    expect(listingMetadata({ page: "2" })).toEqual({
      title: { absolute: "インターン・本選考 募集一覧（2ページ目） | relua" },
      description: "現在応募できるインターン・本選考・イベントの募集一覧、2ページ目です。締切や応募条件を比較できます。",
      openGraph: {
        title: "インターン・本選考 募集一覧（2ページ目）",
        description: "現在応募できるインターン・本選考・イベントの募集一覧、2ページ目です。締切や応募条件を比較できます。",
        url: "/?page=2",
      },
      twitter: {
        title: "インターン・本選考 募集一覧（2ページ目）",
        description: "現在応募できるインターン・本選考・イベントの募集一覧、2ページ目です。締切や応募条件を比較できます。",
      },
      alternates: { canonical: "/?page=2" },
      robots: { index: true, follow: true, googleBot: googleBot(true) },
    });
    expect(listingMetadata({ industry: "industry-01" }, { catalog, resultTotal: 10 })).toEqual({
      title: { absolute: "IT・通信のインターン・新卒採用情報 | relua" },
      description: "IT・通信のインターン・本選考・イベントを比較できます。応募締切、対象学年、開催形式を確認し、企業の公式サイトから応募できます。",
      openGraph: {
        title: "IT・通信のインターン・新卒採用情報",
        description: "IT・通信のインターン・本選考・イベントを比較できます。応募締切、対象学年、開催形式を確認し、企業の公式サイトから応募できます。",
        url: "/?industry=industry-01",
      },
      twitter: {
        title: "IT・通信のインターン・新卒採用情報",
        description: "IT・通信のインターン・本選考・イベントを比較できます。応募締切、対象学年、開催形式を確認し、企業の公式サイトから応募できます。",
      },
      alternates: { canonical: "/?industry=industry-01" },
      robots: { index: true, follow: true, googleBot: googleBot(true) },
    });
  });
});

const opportunity = {
  id: "uuid-1",
  public_code: "ABC12345",
  url: "https://relua.example/opportunities/ABC12345",
  recruitment_status: { id: 2, slug: "status-02", name: "募集中" },
  company: { id: 1, name: "テスト株式会社", public_code: "CMPNY001", url: "https://relua.example/companies/CMPNY001" },
  industry: { id: 1, slug: "industry-01", name: "IT・通信" },
  sector: { id: 1, slug: "sector-1-01", name: "ソフトウェア" },
  event_name: "28卒 エンジニア本選考",
  deadline: "2099-08-31",
  event_type: { id: 2, slug: "type-02", name: "本選考" },
  description: "ソフトウェアエンジニアとしてプロダクト開発に取り組む新卒採用です。",
  event_format: { id: 3, slug: "format-03", name: "ハイブリッド" },
  location: "東京都",
  selection_process: null,
  homepage_url: "https://company.example/",
  job_categories: [],
  tags: [],
  event_start_date: null,
  event_end_date: null,
  period_note: null,
  requirements: null,
  compensation: null,
  graduation_years: [{ id: 3, slug: "grad-03", name: "28卒" }],
  degrees: [],
  audience_note: null,
  recruitment_start_date: null,
  entry_url: "https://company.example/entry",
  source_url: "https://company.example/recruit",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-02T00:00:00Z",
  source_checked_at: "2026-08-03T00:00:00Z",
} satisfies Opportunity;

describe("opportunityMetadata", () => {
  it("uses the public code as a self-canonical and keeps active records indexable", () => {
    expect(opportunityMetadata(opportunity)).toMatchObject({
      title: "テスト株式会社 28卒 エンジニア本選考",
      alternates: { canonical: "/opportunities/ABC12345" },
      openGraph: { url: "/opportunities/ABC12345" },
      robots: { index: true, follow: true },
    });
  });

  it("keeps ended records crawlable but removes them from search results", () => {
    expect(opportunityMetadata({
      ...opportunity,
      recruitment_status: { id: 3, slug: "status-03", name: "締切" },
    }).robots).toMatchObject({ index: false, follow: true });
  });
});

const company = {
  id: 1,
  public_code: "CMPNY001",
  url: "https://relua.example/companies/CMPNY001",
  name: "テスト株式会社",
  business_summary: "業務システムの受託開発と自社SaaSの提供を行っている。",
  description: "受託開発では販売管理と生産管理の領域を担当し、自社SaaSは在庫管理と実績集計の2製品を提供している。",
  business_areas: [{ name: "受託開発事業", description: "販売管理・生産管理システムを個別に開発している。" }],
  website_url: "https://company.example/",
  industries: [],
  current_opportunity_count: 1,
  openings_updated_at: "2026-08-02T00:00:00Z",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-02T00:00:00Z",
  current_opportunities: [opportunity],
  past_opportunities: [],
} satisfies CompanyDetail;

describe("companyMetadata", () => {
  it("self-canonicals on the public code and indexes a described, hiring company", () => {
    expect(companyIsIndexable(company)).toBe(true);
    expect(companyMetadata(company)).toMatchObject({
      title: "テスト株式会社のインターン・本選考情報",
      alternates: { canonical: "/companies/CMPNY001" },
      openGraph: { url: "/companies/CMPNY001" },
      robots: { index: true, follow: true },
    });
  });

  it("requires both halves of the written profile before indexing", () => {
    expect(companyIsIndexable({ ...company, description: null })).toBe(false);
    expect(companyIsIndexable({ ...company, description: "   " })).toBe(false);
    expect(companyIsIndexable({ ...company, business_summary: null })).toBe(false);
    expect(companyIsIndexable({ ...company, business_summary: "   " })).toBe(false);
    expect(companyMetadata({ ...company, business_summary: null, description: null }).robots)
      .toMatchObject({ index: false, follow: true });
  });

  it("describes the company with its lead sentence rather than the body", () => {
    expect(companyMetadata(company).description)
      .toContain("業務システムの受託開発と自社SaaSの提供を行っている。");
  });

  it("keeps a company with no current opening out of search", () => {
    const closed = {
      ...company,
      current_opportunity_count: 0,
      current_opportunities: [],
    } satisfies CompanyDetail;
    expect(companyIsIndexable(closed)).toBe(false);
    expect(companyMetadata(closed).description).toContain("現在掲載中の募集はありません");
  });

  it("does not index a company whose only opening has already ended", () => {
    expect(companyIsIndexable({
      ...company,
      current_opportunities: [{ ...opportunity, deadline: "2020-01-01" }],
    })).toBe(false);
  });
});
