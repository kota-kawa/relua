"use client";

import { useEffect, useState } from "react";

import { useNavigationPending } from "@/lib/navigation-progress";

/** Navigations shorter than this never show the bar; a flash reads as a glitch. */
const APPEAR_AFTER_MS = 140;
/** Covers the fade in globals.css, with a frame to spare. */
const COMPLETE_MS = 300;

type Phase = "idle" | "loading" | "done";

/**
 * A thin line across the top of the viewport while a navigation is in flight.
 *
 * The router keeps the current page on screen until the next one is ready, so
 * without this a click on a filter or a page number is answered by nothing at
 * all until the whole result set swaps. The bar fills on a decelerating curve
 * that never reaches the end on its own — arrival is what ends it.
 */
export function RouteProgress() {
  const pending = useNavigationPending();
  const [phase, setPhase] = useState<Phase>("idle");
  const [tracked, setTracked] = useState(pending);

  /* The arrival of the page is what ends the bar, so the ending is worked out
     while rendering the answer rather than in an effect after it — an effect
     would paint one more frame of a bar that is already finished. Only a bar
     that actually became visible has an ending to play out. */
  if (tracked !== pending) {
    setTracked(pending);
    if (!pending) setPhase((current) => (current === "loading" ? "done" : "idle"));
  }

  useEffect(() => {
    if (!pending) return;
    const appear = window.setTimeout(() => setPhase("loading"), APPEAR_AFTER_MS);
    return () => window.clearTimeout(appear);
  }, [pending]);

  useEffect(() => {
    if (phase !== "done") return;
    const clear = window.setTimeout(() => setPhase("idle"), COMPLETE_MS);
    return () => window.clearTimeout(clear);
  }, [phase]);

  if (phase === "idle") return null;
  /* The filter panel and the sort menu already announce their own updates to
     assistive technology, so this stays decorative rather than repeating them. */
  return <div className="route-progress" data-phase={phase} aria-hidden="true" />;
}
