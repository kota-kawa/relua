import { DeadlineCalendar } from "@/components/deadline-calendar";
import { DiscoveryNav } from "@/components/discovery-nav";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { FilterPanel } from "@/components/filter-panel";
import { Hero } from "@/components/hero";
import { OpportunityCard } from "@/components/opportunity-card";
import { OpportunityTable } from "@/components/opportunity-table";
import { Pagination } from "@/components/pagination";
import { SlidersHorizontal } from "@/components/icons";
import { getMasters, getOpportunities } from "@/lib/api";
import type { SearchParams } from "@/lib/types";

export default async function Home({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const requestedView = Array.isArray(params.view) ? params.view[0] : params.view;
  const view = requestedView === "list" || requestedView === "calendar" ? requestedView : "cards";
  let data;
  try {
    data = await Promise.all([getMasters(), getOpportunities(params)]);
  } catch {
    return <ErrorState />;
  }
  const [masters, result] = data;
  const query = Array.isArray(params.q) ? params.q[0] : params.q;
  const sort = Array.isArray(params.sort) ? params.sort[0] : params.sort;
  return (
    <main>
        <Hero defaultQuery={query} total={result.total} />
        <DiscoveryNav params={params} view={view} />
        <section className={`results-section view-${view}`}>
          <div className="shell result-layout">
            <FilterPanel masters={masters} params={params} />
            <div className="results-main">
              <div className="results-toolbar">
                <div>
                  <p className="results-kicker">{view === "calendar" ? "DEADLINE CALENDAR" : "OPPORTUNITIES"}</p>
                  <h2>{query ? `「${query}」の検索結果` : view === "calendar" ? "締切から募集を探す" : "募集中の機会を探す"}</h2>
                  <p><strong>{result.total.toLocaleString("ja-JP")}</strong> 件を表示しています</p>
                </div>
                <form action="/" method="get" className="sort-form">
                  {Object.entries(params).flatMap(([key, value]) => {
                    if (key === "sort" || key === "page") return [];
                    const values = Array.isArray(value) ? value : value ? [value] : [];
                    return values.map((entry) => <input key={`${key}-${entry}`} type="hidden" name={key} value={entry} />);
                  })}
                  <SlidersHorizontal size={16} />
                  <label htmlFor="sort" className="sr-only">並び順</label>
                  <select id="sort" name="sort" defaultValue={sort ?? "deadline"} onChange={undefined}>
                    <option value="deadline">締切が近い順</option>
                    <option value="updated">更新が新しい順</option>
                    <option value="created">掲載が新しい順</option>
                  </select>
                  <button type="submit">並び替え</button>
                </form>
              </div>

              {result.items.length ? (
                <>
                  {view === "list" ? <OpportunityTable items={result.items} /> : view === "calendar" ? (
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
