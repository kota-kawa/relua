"use client";

import Link, { useLinkStatus } from "next/link";
import type { ComponentProps } from "react";

import { useReportNavigation } from "@/lib/navigation-progress";

/**
 * `useLinkStatus` only reads the status of the link it is rendered inside, so
 * the reporter has to be a child of the `Link` rather than a wrapper around it.
 * It renders nothing: the visible feedback is the shared progress indicator in
 * the root layout.
 */
function NavigationReporter() {
  const { pending } = useLinkStatus();
  useReportNavigation(pending);
  return null;
}

/**
 * A `next/link` that announces its own in-flight navigation. Use it wherever a
 * click leaves the reader waiting: the router holds the current page on screen
 * until the next one is ready, so a filter, a page number, a view or a listing
 * that takes a moment to fetch would otherwise answer the click with nothing.
 */
export function NavLink({ children, ...props }: ComponentProps<typeof Link>) {
  return (
    <Link {...props}>
      {children}
      <NavigationReporter />
    </Link>
  );
}
