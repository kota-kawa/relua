/**
 * Opening a listing used to fall back to the root skeleton, which is the
 * *listing* page in outline — a filter column and a grid of cards — so the step
 * between a card and its detail page went through a shape belonging to neither.
 * This one holds the detail page's own frame instead: the navy header block, the
 * action row, the text column and the summary panel beside it.
 */
export default function Loading() {
  return (
    <main className="detail-page loading-page">
      <div className="shell">
        <div className="loading-back" />
        <div className="loading-detail-hero" />
        <div className="loading-detail-actions" />
        <div className="loading-detail-layout">
          <div className="loading-detail-main">
            {Array.from({ length: 3 }, (_, index) => <div className="loading-detail-block" key={index} />)}
          </div>
          <div className="loading-detail-side" />
        </div>
      </div>
    </main>
  );
}
