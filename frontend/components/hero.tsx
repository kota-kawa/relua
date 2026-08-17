import { HeroHoneycomb } from "@/components/hero-honeycomb";
import { Search } from "@/components/icons";

export function Hero({
  defaultQuery,
  heading,
  children,
}: {
  defaultQuery?: string;
  heading?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <section className="hero">
      <HeroHoneycomb />
      <div className="shell hero-inner">
        <div className="hero-copy">
          <h1>{heading ?? "インターン・本選考・イベントを横断検索"}</h1>
        </div>

        <form action="/" method="get" className="hero-search" role="search">
          <Search size={23} aria-hidden="true" />
          <label className="sr-only" htmlFor="hero-q">企業名、イベント名、キーワードで検索</label>
          <input
            id="hero-q"
            type="search"
            name="q"
            defaultValue={defaultQuery}
            placeholder="企業名・職種で検索"
            autoComplete="off"
          />
          <button type="submit">検索する</button>
        </form>

        {children}
      </div>
    </section>
  );
}
