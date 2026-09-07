import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { CategoryDirectory } from "@/components/category-directory";
import { CategoryOverview } from "@/components/category-overview";
import { DeadlineCalendar } from "@/components/deadline-calendar";
import { DiscoveryNav, type ViewMode } from "@/components/discovery-nav";
import { EmptyState } from "@/components/empty-state";
import { FilterPanel } from "@/components/filter-panel";
import { Hero } from "@/components/hero";
import { JsonLd } from "@/components/json-ld";
import { OpportunityCard } from "@/components/opportunity-card";
import { OpportunityTable } from "@/components/opportunity-table";
import { Pagination } from "@/components/pagination";
import { QuickFilters } from "@/components/quick-filters";
import { SortForm } from "@/components/sort-form";
import { withDefaultOpenStatus } from "@/lib/format";
import { getListingSeo, getSeoFacetCatalog, listingMetadata } from "@/lib/seo";
import { loadListingSnapshot } from "@/lib/seo-data";
import { listingStructuredData } from "@/lib/structured-data";
import type { SearchParams } from "@/lib/types";

function first(params: SearchParams, key: string) {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}

export async function generateMetadata({ searchParams }: { searchParams: Promise<SearchParams> }): Promise<Metadata> {
  const params = withDefaultOpenStatus(await searchParams);
  const { masters, result } = await loadListingSnapshot(params);
  const catalog = getSeoFacetCatalog(masters);
  const preliminary = getListingSeo(params, { catalog });
  const requestedPage = Number(first(params, "page") ?? 1);
  if (Number.isSafeInteger(requestedPage) && requestedPage > 1 && requestedPage > result.total_pages) notFound();
  if (preliminary.facet && result.total === 0) notFound();
  return listingMetadata(params, {
    catalog,
    resultTotal: result.total,
    totalPages: result.total_pages,
  });
}

export default async function Home({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = withDefaultOpenStatus(await searchParams);
  const requestedView = first(params, "view");
  const view: ViewMode = requestedView === "list" || requestedView === "calendar" ? requestedView : "cards";
  const { masters, result } = await loadListingSnapshot(params);
  if (result.page > 1 && result.page > result.total_pages) notFound();
  const listingSeo = getListingSeo(params, {
    catalog: getSeoFacetCatalog(masters),
    resultTotal: result.total,
    totalPages: result.total_pages,
  });
  if (listingSeo.facet && result.total === 0) notFound();
  const categoryLabel = listingSeo.facet?.label;
  const categoryHeading = categoryLabel
    ? `${categoryLabel}${listingSeo.facet?.key === "graduation_year" ? "向け" : "の"}募集情報`
    : undefined;
  const query = first(params, "q");
  const sort = first(params, "sort");
  /* Remount key for the results. Every listing navigation lands on the same
     page component, so React reuses the DOM it can match and the arrival of a
     new result set would pass without a frame of motion. Keying the block on
     the request makes each set enter as one. */
  const resultsKey = Object.entries(params)
    .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join(",") : value ?? ""}`)
    .sort()
    .join("&");

  return (
    <main className="page-enter">
      {listingSeo.index && <JsonLd data={listingStructuredData(result.items, result.page, result.per_page)} />}
      <Hero defaultQuery={query} heading={categoryHeading}>
        <QuickFilters masters={masters} params={params} />
      </Hero>
      {listingSeo.facet && result.page === 1 && (
        <CategoryOverview facet={listingSeo.facet} total={result.total} />
      )}
      <DiscoveryNav masters={masters} params={params} view={view} total={result.total} />
      <section className={`results-section view-${view}`}>
        <div className="shell result-layout">
          <FilterPanel masters={masters} params={params} total={result.total} />
          <div className="results-main">
            <div className="results-toolbar">
              <h2>
                {query ? `「${query}」の検索結果` : categoryHeading ?? (view === "calendar" ? "締切が近い順" : "募集一覧")}
                <span><strong>{result.total.toLocaleString("ja-JP")}</strong> 件</span>
              </h2>
              {/* The calendar groups by month, so it is always deadline-ordered. */}
              {view !== "calendar" && <SortForm params={params} value={sort ?? (query ? "relevance" : "deadline")} />}
            </div>

            <div className="results-flow" key={resultsKey}>
              {result.items.length ? (
                <>
                  {view === "list" ? (
                    <OpportunityTable items={result.items} />
                  ) : view === "calendar" ? (
                    <DeadlineCalendar items={result.items} />
                  ) : (
                    <div className="card-grid">
                      {result.items.map((item, index) => <OpportunityCard key={item.id} item={item} index={index} />)}
                    </div>
                  )}
                  <Pagination page={result.page} totalPages={result.total_pages} params={params} />
                </>
              ) : <EmptyState />}
            </div>
          </div>
        </div>
      </section>
      {listingSeo.index && !listingSeo.facet && result.page === 1 && (
        <CategoryDirectory masters={masters} />
      )}
    </main>
  );
}
