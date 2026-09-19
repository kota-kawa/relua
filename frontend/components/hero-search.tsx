"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Search } from "@/components/icons";
import { useReportNavigation } from "@/lib/navigation-progress";

/**
 * A plain GET form to `/` is the fallback and stays the markup, so the search
 * still works without JavaScript. With it, the submit is routed instead: a form
 * navigation tears the document down and rebuilds it — a white flash and a
 * fresh hero on every search — where a client navigation leaves the page in
 * place until the results are ready.
 */
export function HeroSearch({ defaultQuery }: { defaultQuery?: string }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  useReportNavigation(isPending);

  return (
    <form
      action="/"
      method="get"
      className="hero-search"
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        const query = new FormData(event.currentTarget).get("q");
        // Same destination the browser would have built from this form, so the
        // scripted and unscripted paths cannot drift apart.
        const search = typeof query === "string" && query ? `?${new URLSearchParams({ q: query })}` : "";
        startTransition(() => router.push(`/${search}`));
      }}
    >
      <Search size={23} aria-hidden="true" />
      <label className="sr-only" htmlFor="hero-q">企業名、イベント名、キーワードで検索</label>
      <input
        id="hero-q"
        type="search"
        name="q"
        defaultValue={defaultQuery}
        placeholder="企業名・職種で検索"
        autoComplete="off"
        // Mirrors the internal API's own `max_length=100` on `q` (see
        // `lib/api.ts`'s `listingApiParams`), so a visitor sees the limit at
        // the input instead of having it silently trimmed after submit.
        maxLength={100}
      />
      <button type="submit">検索する</button>
    </form>
  );
}
