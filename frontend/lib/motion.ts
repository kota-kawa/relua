import type { CSSProperties } from "react";

/**
 * Shared motion helpers.
 *
 * Entrance animations are driven from CSS; the only thing the markup has to
 * supply is each item's position in its list, so the delays can cascade.
 */

/**
 * Items past this position share the last delay. A results page can hold 60
 * calendar rows, and a strict cascade would make the last one arrive two
 * seconds after the first — long enough to read as a page that is still
 * loading rather than one that has arrived.
 */
export const STAGGER_LIMIT = 7;

/** Position in the list, capped, for the CSS cascade to base its delay on. */
export function stagger(index: number): CSSProperties {
  return { "--stagger": Math.min(Math.max(index, 0), STAGGER_LIMIT) } as CSSProperties;
}
