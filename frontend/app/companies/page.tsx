import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { JsonLd } from "@/components/json-ld";
import { Pagination } from "@/components/pagination";
import { loadCompanyDirectorySnapshot } from "@/lib/seo-data";
import { companyPath } from "@/lib/site";
import { companyDirectoryStructuredData } from "@/lib/structured-data";
import type { CompanySummary, SearchParams } from "@/lib/types";

const DIRECTORY_PATH = "/companies";

/**
 * Unlike the listing, an unusable `page` here is a 404 rather than a `noindex`
 * page of results. The listing has to keep serving one because a filter URL can
 * carry a broken page alongside filters worth showing; this route has nothing
 * else to show, so the honest answer is that the URL does not exist. Unknown
 * query keys are ignored instead, since campaign parameters on an inbound link
 * must not turn a real page into a 404.
 */
function directoryPageNumber(params: SearchParams) {
  const value = params.page;
  if (value === undefined) return 1;
  if (Array.isArray(value) || !/^\d+$/.test(value)) return null;
  const page = Number(value);
  return Number.isSafeInteger(page) && page >= 1 ? page : null;
}

async function loadDirectory(searchParams: Promise<SearchParams>) {
  const page = directoryPageNumber(await searchParams);
  if (page === null) notFound();
  const { result } = await loadCompanyDirectorySnapshot(page);
  // `total_pages` is at least 1, so an empty directory still serves page 1.
  if (page > result.total_pages) notFound();
  return { page, result };
}

export async function generateMetadata(
  { searchParams }: { searchParams: Promise<SearchParams> },
): Promise<Metadata> {
  const { page, result } = await loadDirectory(searchParams);
  const title = page > 1 ? `掲載企業一覧（${page}ページ目）` : "掲載企業一覧";
  const description = `reluaに事業内容を掲載している企業${result.total.toLocaleString("ja-JP")}社の一覧です。`
    + "各社が何をしている会社かを読み、そのままインターン・本選考の募集を確認できます。"
    + (page > 1 ? `${page}ページ目です。` : "");
  const canonical = page > 1 ? `${DIRECTORY_PATH}?page=${page}` : DIRECTORY_PATH;

  return {
    title,
    description,
    alternates: { canonical },
    openGraph: { title, description, url: canonical, type: "website" },
    twitter: { title, description },
    robots: {
      index: true,
      follow: true,
      googleBot: { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1, "max-video-preview": -1 },
    },
  };
}

function CompanyEntry({ company }: { company: CompanySummary }) {
  const industries = company.industries
    .filter((entry) => entry.is_primary)
    .map((entry) => (entry.sector ? `${entry.industry.name} / ${entry.sector.name}` : entry.industry.name));

  return (
    <li className="company-entry">
      <h2>
        <Link href={companyPath(company.public_code)}>{company.name}</Link>
      </h2>
      {company.business_summary && <p className="company-entry-summary">{company.business_summary}</p>}
      <p className="company-entry-meta">
        {industries.map((label) => <span key={label}>{label}</span>)}
        <span className="company-entry-openings">
          {company.current_opportunity_count > 0
            ? `掲載中の募集 ${company.current_opportunity_count}件`
            : "現在の募集なし"}
        </span>
      </p>
    </li>
  );
}

export default async function CompanyDirectoryPage(
  { searchParams }: { searchParams: Promise<SearchParams> },
) {
  const { page, result } = await loadDirectory(searchParams);

  return (
    <main className="directory-page page-enter">
      <JsonLd data={companyDirectoryStructuredData(result.items, page, result.per_page)} />
      <section className="directory-intro">
        <div className="shell">
          <p className="eyebrow">COMPANIES</p>
          <h1>掲載企業一覧</h1>
          <p className="directory-lead">
            事業内容を掲載している企業の一覧です。何をしている会社かを読んでから、その企業の募集を確認できます。
            募集の有無にかかわらず、過去に募集を掲載した企業のページも残しています。
          </p>
          <p className="directory-count"><strong>{result.total.toLocaleString("ja-JP")}</strong> 社</p>
        </div>
      </section>
      <div id="listings" className="listings-anchor" aria-hidden="true" />
      <section className="directory-body">
        <div className="shell">
          {result.items.length > 0 ? (
            <>
              <ul className="company-entry-list">
                {result.items.map((company) => <CompanyEntry key={company.id} company={company} />)}
              </ul>
              <Pagination
                page={page}
                totalPages={result.total_pages}
                params={{}}
                basePath={DIRECTORY_PATH}
              />
            </>
          ) : (
            <p className="company-empty">掲載中の企業情報はまだありません。</p>
          )}
        </div>
      </section>
    </main>
  );
}
