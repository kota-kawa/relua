import { describe, expect, it } from "vitest";

import { canonicalHostUrl, legacyOpportunityId } from "./proxy";

describe("legacy opportunity URL matching", () => {
  it("matches internal UUID detail paths", () => {
    expect(legacyOpportunityId("/opportunities/e87f7f74-b5da-4b14-bc9b-5302146cd87d"))
      .toBe("e87f7f74-b5da-4b14-bc9b-5302146cd87d");
  });

  it("leaves canonical public codes and unrelated paths alone", () => {
    expect(legacyOpportunityId("/opportunities/A8MFMKFD")).toBeNull();
    expect(legacyOpportunityId("/saved")).toBeNull();
  });
});

describe("canonical host matching", () => {
  it("preserves path and query while moving www to the configured apex host", () => {
    expect(canonicalHostUrl(
      "https://www.relua.example/opportunities/ABC12345?from=test",
      "www.relua.example",
      "https://relua.example",
    )?.toString()).toBe("https://relua.example/opportunities/ABC12345?from=test");
  });

  it("does not redirect the canonical or an unrelated host", () => {
    expect(canonicalHostUrl("https://relua.example/", "relua.example", "https://relua.example")).toBeNull();
    expect(canonicalHostUrl("https://other.example/", "other.example", "https://relua.example")).toBeNull();
  });
});
