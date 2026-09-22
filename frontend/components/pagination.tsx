"use client";

import { ArrowLeft, ArrowRight } from "@/components/icons";
import { NavLink } from "@/components/nav-link";
import { withQuery } from "@/lib/format";
import type { SearchParams } from "@/lib/types";

/**
 * Turning a page replaces the whole list, so the reader has to be taken back to
 * the top of it — but the destination is scrolled to here rather than through a
 * `#listings` href. A hash would stay in the URL and be replayed on every later
 * return to this page, overriding the position the reader had actually reached
 * when they opened a listing. Scrolling on the click keeps that to the one
 * navigation it belongs to, and gives the new page a head start by moving the
 * viewport before its content arrives.
 */
function scrollToResults(event: React.MouseEvent<HTMLAnchorElement>) {
  // Opening the page in a new tab or window must leave this one where it is.
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  document.getElementById("listings")?.scrollIntoView();
}

export function Pagination(
  { page, totalPages, params, basePath = "/" }:
  { page: number; totalPages: number; params: SearchParams; basePath?: string },
) {
  if (totalPages <= 1) return null;
  const pages = Array.from({ length: totalPages }, (_, index) => index + 1).filter(
    (value) => value === 1 || value === totalPages || Math.abs(value - page) <= 1,
  );
  const href = (value: number) => withQuery(params, { page: String(value) }, basePath);
  return (
    <nav className="pagination" aria-label="ページネーション">
      {page > 1 ? (
        <NavLink className="page-arrow" scroll={false} onClick={scrollToResults} href={href(page - 1)}><ArrowLeft size={17} /> 前へ</NavLink>
      ) : <span className="page-arrow disabled"><ArrowLeft size={17} /> 前へ</span>}
      <div className="page-numbers">
        {pages.map((value, index) => (
          <span key={value} className="page-number-wrap">
            {index > 0 && pages[index - 1] !== value - 1 && <i>…</i>}
            <NavLink className={value === page ? "active" : ""} scroll={false} onClick={scrollToResults} href={href(value)}>{value}</NavLink>
          </span>
        ))}
      </div>
      {/* Mobile replaces the number list with a compact position indicator. */}
      <span className="page-position">{page} / {totalPages}</span>
      {page < totalPages ? (
        <NavLink className="page-arrow" scroll={false} onClick={scrollToResults} href={href(page + 1)}>次へ <ArrowRight size={17} /></NavLink>
      ) : <span className="page-arrow disabled">次へ <ArrowRight size={17} /></span>}
    </nav>
  );
}
