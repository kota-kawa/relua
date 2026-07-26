export default function Loading() {
  return (
    <main>
      <div className="loading-hero" />
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
