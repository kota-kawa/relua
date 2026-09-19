"use client";

import Link from "next/link";
import { useEffect } from "react";

/**
 * The site had no error boundary at all: an uncaught throw anywhere in a page's
 * render or `generateMetadata` — an SEO snapshot outage
 * (`SeoDataUnavailableError`), an unretried 4xx/5xx from the internal API, or
 * any other unexpected failure — fell through to Next.js's bare framework
 * error screen, which carries none of the site's chrome and no way back to a
 * working page. Next.js also runs `generateMetadata` under this same boundary,
 * so this covers metadata-time failures too, not just the page body.
 *
 * `global-error.tsx` is deliberately not added alongside this: nothing in
 * `app/layout.tsx` performs data fetching that can fail per request (only
 * `siteOrigin()`, which is a startup-time configuration check, not a
 * per-request one), so a root-layout-level boundary has nothing of its own to
 * catch here.
 */
export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // No client-side analytics call exists for this today; the console entry
    // is what shows up next to the platform's own server-side error log.
    console.error(error);
  }, [error]);

  return (
    <main className="shell error-state page-enter">
      <p className="eyebrow">ERROR</p>
      <h1>一時的に読み込めませんでした</h1>
      <p>時間をおいてもう一度お試しください。改善しない場合は、しばらく経ってから再度アクセスしてください。</p>
      <div style={{ display: "flex", justifyContent: "center", gap: 16 }}>
        <button
          type="button"
          onClick={() => reset()}
          style={{
            display: "inline-flex",
            marginTop: 16,
            paddingBottom: 4,
            border: "none",
            borderBottom: "1px solid var(--orange)",
            background: "none",
            color: "var(--orange)",
            font: "inherit",
            fontSize: 13,
            fontWeight: 750,
            cursor: "pointer",
          }}
        >
          もう一度試す
        </button>
        <Link href="/">募集一覧へ戻る</Link>
      </div>
    </main>
  );
}
