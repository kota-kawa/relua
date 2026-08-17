import type { Metadata } from "next";

import { DeadlineCalendar } from "@/components/deadline-calendar";
import { DiscoveryNav, type ViewMode } from "@/components/discovery-nav";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { FilterPanel } from "@/components/filter-panel";
import { Hero } from "@/components/hero";
import { OpportunityCard } from "@/components/opportunity-card";
import { OpportunityTable } from "@/components/opportunity-table";
import { Pagination } from "@/components/pagination";
import { QuickFilters } from "@/components/quick-filters";
import { SortForm } from "@/components/sort-form";
import { getMasters, getOpportunities } from "@/lib/api";
import { withDefaultOpenStatus } from "@/lib/format";
import { listingMetadata } from "@/lib/seo";
import type { SearchParams } from "@/lib/types";

function first(params: SearchParams, key: string) {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}

export async function generateMetadata({ searchParams }: { searchParams: Promise<SearchParams> }): Promise<Metadata> {
  return listingMetadata(await searchParams);
}

export default async function Home({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = withDefaultOpenStatus(await searchParams);
  const requestedView = first(params, "view");
  const view: ViewMode = requestedView === "list" || requestedView === "calendar" ? requestedView : "cards";
  let data;
  try {
    data = await Promise.all([getMasters(), getOpportunities(params)]);
  } catch {
    return <ErrorState />;
  }
  const [masters, result] = data;
  const query = first(params, "q");
  const sort = first(params, "sort");

  return (
    <main>
      <Hero defaultQuery={query}>
        <QuickFilters masters={masters} params={params} />
      </Hero>
      <DiscoveryNav masters={masters} params={params} view={view} total={result.total} />
      <section className={`results-section view-${view}`}>
        <div className="shell result-layout">
          <FilterPanel masters={masters} params={params} total={result.total} />
          <div className="results-main">
            <div className="results-toolbar">
              <h2>
                {query ? `「${query}」の検索結果` : view === "calendar" ? "締切が近い順" : "募集一覧"}
                <span><strong>{result.total.toLocaleString("ja-JP")}</strong> 件</span>
              </h2>
              {/* The calendar groups by month, so it is always deadline-ordered. */}
              {view !== "calendar" && <SortForm params={params} value={sort ?? (query ? "relevance" : "deadline")} />}
            </div>

            {result.items.length ? (
              <>
                {view === "list" ? (
                  <OpportunityTable items={result.items} />
                ) : view === "calendar" ? (
                  <DeadlineCalendar items={result.items} />
                ) : (
                  <div className="card-grid">
                    {result.items.map((item) => <OpportunityCard key={item.id} item={item} />)}
                  </div>
                )}
                <Pagination page={result.page} totalPages={result.total_pages} params={params} />
              </>
            ) : <EmptyState />}
          </div>
        </div>
      </section>
    </main>
  );
}
