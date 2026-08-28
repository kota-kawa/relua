// @vitest-environment jsdom

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Masters } from "@/lib/types";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a href={String(href)} {...props}>{children}</a>,
}));

import { DiscoveryNav } from "./discovery-nav";

const masters = {
  recruitment_statuses: [],
  industries: [],
  sectors: [],
  event_types: [],
  event_formats: [],
  job_categories: [],
  graduation_years: [],
  degrees: [],
} as unknown as Masters;

afterEach(() => cleanup());

describe("the #listings scroll target", () => {
  it("sits in normal flow just above the sticky bar", () => {
    const { container } = render(<DiscoveryNav masters={masters} params={{}} view="cards" total={0} />);

    const anchor = container.querySelector("#listings");
    const bar = container.querySelector(".discovery-bar");
    expect(anchor).not.toBeNull();
    /* A sticky element is already parked at the top of the viewport, so the
       router would either not move at all or skip past it — the anchor has to
       be a separate element that scrolls with the page. */
    expect(anchor).not.toBe(bar);
    expect(anchor?.nextElementSibling).toBe(bar);
  });
});
