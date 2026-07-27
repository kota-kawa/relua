import Link from "next/link";

import { ArrowLeft, ArrowRight } from "@/components/icons";
import { withQuery } from "@/lib/format";
import type { SearchParams } from "@/lib/types";

export function Pagination({ page, totalPages, params }: { page: number; totalPages: number; params: SearchParams }) {
  if (totalPages <= 1) return null;
  const pages = Array.from({ length: totalPages }, (_, index) => index + 1).filter(
    (value) => value === 1 || value === totalPages || Math.abs(value - page) <= 1,
  );
  return (
    <nav className="pagination" aria-label="ページネーション">
      {page > 1 ? (
        <Link className="page-arrow" href={withQuery(params, { page: String(page - 1) })}><ArrowLeft size={17} /> 前へ</Link>
      ) : <span className="page-arrow disabled"><ArrowLeft size={17} /> 前へ</span>}
      <div className="page-numbers">
        {pages.map((value, index) => (
          <span key={value} className="page-number-wrap">
            {index > 0 && pages[index - 1] !== value - 1 && <i>…</i>}
            <Link className={value === page ? "active" : ""} href={withQuery(params, { page: String(value) })}>{value}</Link>
          </span>
        ))}
      </div>
      {/* Mobile replaces the number list with a compact position indicator. */}
      <span className="page-position">{page} / {totalPages}</span>
      {page < totalPages ? (
        <Link className="page-arrow" href={withQuery(params, { page: String(page + 1) })}>次へ <ArrowRight size={17} /></Link>
      ) : <span className="page-arrow disabled">次へ <ArrowRight size={17} /></span>}
    </nav>
  );
}
