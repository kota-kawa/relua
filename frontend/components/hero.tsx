import { HeroHoneycomb } from "@/components/hero-honeycomb";
import { HeroSearch } from "@/components/hero-search";

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

        <HeroSearch defaultQuery={defaultQuery} />

        {children}
      </div>
    </section>
  );
}
