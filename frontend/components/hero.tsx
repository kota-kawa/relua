import { Search } from "@/components/icons";

export function Hero({ defaultQuery }: { defaultQuery?: string }) {
  return (
    <section className="hero">
      <div className="hero-grid" aria-hidden="true" />
      <div className="shell hero-inner">
        <div className="hero-copy">
          <h1>インターン・本選考・イベントを横断検索</h1>
          <p className="hero-lead">締切・卒業年度・職種で絞り込み。出典リンク付き、登録不要。</p>
        </div>

        <form action="/" method="get" className="hero-search" role="search">
          <Search size={23} aria-hidden="true" />
          <label className="sr-only" htmlFor="hero-q">企業名、イベント名、キーワードで検索</label>
          <input
            id="hero-q"
            type="search"
            name="q"
            defaultValue={defaultQuery}
            placeholder="企業名、職種、キーワードで検索"
            autoComplete="off"
          />
          <button type="submit">検索する</button>
        </form>
      </div>
    </section>
  );
}
