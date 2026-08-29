export default function Loading() {
  return (
    <main className="loading-page">
      <div className="loading-hero" />
      {/* The skeleton stands in for the listing page while its data loads, and a
          navigation to `#listings` can land on it. Carrying the same anchor, at
          the same place in the layout, keeps that jump on target instead of
          falling back to the top of the document. */}
      <div id="listings" className="listings-anchor" aria-hidden="true" />
      <div className="loading-tabs" />
      <div className="shell loading-layout">
        <div className="loading-filter" />
        <div className="loading-grid">
          {Array.from({ length: 6 }, (_, index) => <div className="loading-card" key={index} />)}
        </div>
      </div>
    </main>
  );
}
