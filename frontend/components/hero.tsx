import { Search, Sparkles } from "@/components/icons";

export function Hero({ defaultQuery, total }: { defaultQuery?: string; total: number }) {
  return (
    <section className="hero">
      <div className="hero-grid" aria-hidden="true" />
      <div className="shell hero-inner">
        <div className="hero-copy">
          <p className="eyebrow"><Sparkles size={15} /> 信頼できる出典から、ひとつずつ</p>
          <h1>
            探す時間を短く。<span>選ぶ時間を豊かに。</span>
          </h1>
          <p className="hero-lead">
            インターン・本選考・イベントを、締切や職種から横断検索。
          </p>
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

        <div className="hero-meta">
          <span><strong>{total.toLocaleString("ja-JP")}</strong> 件の募集情報</span>
          <span className="hero-divider" />
          <span>すべて無料・登録不要</span>
          <span className="hero-divider" />
          <span>出典リンク付き</span>
        </div>
      </div>
    </section>
  );
}
