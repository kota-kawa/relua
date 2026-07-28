import type { CSSProperties } from "react";

/* The lattice is the relua mark. A signal ignites cells across it from left to
   right, the way a search sweeps the listings — the hive stays still, the query
   travels. Warm cells echo the orange cells in the logo.

   Positions are lattice indices, not pixels: the CSS derives every offset from
   --hex-r, so one variable rescales the whole field per breakpoint. */

const COLUMNS = 32;
const ROWS = 5;

type Cell = { col: number; row: number; warm: boolean };

/* Built once at module scope with a fixed seed, so the server and the client
   render identical markup. Math.random() here would break hydration. */
const CELLS: Cell[] = (() => {
  let seed = 7;
  const next = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;

  const taken = new Set<string>();
  const cells: Cell[] = [];

  for (let col = 0; col < COLUMNS; col += 1) {
    // Most columns light one cell, some light two, so the wave front stays ragged.
    const count = next() < 0.45 ? 2 : 1;
    for (let n = 0; n < count; n += 1) {
      const row = Math.floor(next() * ROWS);
      const warm = next() < 0.16;
      const key = `${col}-${row}`;
      if (taken.has(key)) continue;
      taken.add(key);
      cells.push({ col, row, warm });
    }
  }

  return cells;
})();

export function HeroHoneycomb() {
  return (
    <div className="hive" aria-hidden="true">
      <div className="hive-lattice" />
      {CELLS.map(({ col, row, warm }) => (
        <span
          key={`${col}-${row}`}
          className={warm ? "hive-cell hive-cell-warm" : "hive-cell"}
          style={{
            "--col": col,
            // Odd columns sit half a row lower — that offset is what makes it a
            // honeycomb rather than a grid of hexagons.
            "--row": row + (col % 2 === 1 ? 0.5 : 0),
          } as CSSProperties}
        />
      ))}
    </div>
  );
}
