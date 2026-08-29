import { ActiveFilters } from "@/components/active-filters";
import { ViewSwitcher, type ViewMode } from "@/components/view-switcher";
import type { Masters, SearchParams } from "@/lib/types";

export type { ViewMode };

export function DiscoveryNav({
  masters,
  params,
  view,
  total,
}: {
  masters: Masters;
  params: SearchParams;
  view: ViewMode;
  total: number;
}) {
  return (
    <>
      {/* The bar itself is sticky, and a stuck element already sits at the top
          of the viewport — scrolling to it would either move nothing or, as the
          router skips sticky elements when resolving a hash, land on the
          section below and leave the results heading hidden behind the bar.
          This in-flow marker gives `#listings` a stable position: the point
          where the bar comes to rest and the results begin. */}
      <div id="listings" className="listings-anchor" aria-hidden="true" />
      <div className="discovery-bar">
        <div className="shell discovery-inner">
          <ActiveFilters masters={masters} params={params} total={total} />
          <ViewSwitcher params={params} view={view} />
        </div>
      </div>
    </>
  );
}
