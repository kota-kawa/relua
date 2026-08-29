"use client";

import { useEffect, useSyncExternalStore } from "react";

/**
 * A count of the navigations the app is currently waiting on.
 *
 * App Router navigations keep the current page on screen until the next one is
 * ready, which is the right behaviour — nothing flickers — but it also means a
 * click can look like it did nothing while the server is answering. Every
 * surface that starts a navigation reports it here, and one indicator in the
 * root layout reads the total. A count rather than a flag: a filter change and
 * a link click can overlap, and the last one to finish ends the indication.
 */
let pending = 0;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Opens one navigation; the returned function closes it, and is safe to call twice. */
export function beginNavigation() {
  pending += 1;
  emit();
  let closed = false;
  return () => {
    if (closed) return;
    closed = true;
    pending = Math.max(0, pending - 1);
    emit();
  };
}

export function isNavigationPending() {
  return pending > 0;
}

/** Test seam: navigation counts are module state and outlive a single render. */
export function resetNavigationProgress() {
  pending = 0;
  emit();
}

/**
 * Reports this component's navigation for as long as `pending` holds. The
 * cleanup also covers the component being unmounted by the very navigation it
 * was reporting, which is the usual way a link's pending state ends.
 */
export function useReportNavigation(isPending: boolean) {
  useEffect(() => {
    if (!isPending) return;
    return beginNavigation();
  }, [isPending]);
}

export function useNavigationPending() {
  return useSyncExternalStore(subscribe, isNavigationPending, () => false);
}
