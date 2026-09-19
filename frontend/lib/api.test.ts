import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    body: { cancel: async () => undefined },
  } as unknown as Response;
}

/** What undici rejects with when our own AbortController fires. */
function abortError() {
  return new DOMException("The operation was aborted", "AbortError");
}

/** A request that only ends when the caller's timeout aborts it. */
function hangsUntilAborted(init: { signal: AbortSignal }) {
  return new Promise<Response>((_, reject) => {
    init.signal.addEventListener("abort", () => reject(abortError()));
  });
}

/** api.ts reads its timeout budget once, at import, so each case loads it fresh. */
async function loadApi(timeoutMs: number) {
  vi.resetModules();
  vi.stubEnv("API_INTERNAL_URL", "http://api.test");
  vi.stubEnv("API_INTERNAL_TOKEN", "test-token");
  vi.stubEnv("API_INTERNAL_TIMEOUT_MS", String(timeoutMs));
  return import("./api");
}

/** Same, but deliberately leaves API_INTERNAL_TOKEN unset. */
async function loadApiWithoutToken(nodeEnv: string) {
  vi.resetModules();
  vi.stubEnv("API_INTERNAL_URL", "http://api.test");
  vi.stubEnv("API_INTERNAL_TIMEOUT_MS", "10000");
  vi.stubEnv("NODE_ENV", nodeEnv);
  return import("./api");
}

describe("internal API reads", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("retries a transport failure once and returns the second answer", async () => {
    const { getMasters } = await loadApi(10_000);
    fetchMock
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce(jsonResponse({ industries: [] }));

    await expect(getMasters()).resolves.toEqual({ industries: [] });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retries a 502 from a restarting API", async () => {
    const { getMasters } = await loadApi(10_000);
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "bad gateway" }, 502))
      .mockResolvedValueOnce(jsonResponse({ industries: [] }));

    await expect(getMasters()).resolves.toEqual({ industries: [] });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("gives up after one retry, reports the failure, and releases each body", async () => {
    const { getMasters, ApiError } = await loadApi(10_000);
    const cancel = vi.fn(async () => undefined);
    fetchMock.mockImplementation(async () => ({
      ok: false, status: 503, json: async () => ({ detail: "down" }), body: { cancel },
    } as unknown as Response));

    await expect(getMasters()).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    // An unread body would hold its connection open, which matters most when
    // the API is failing and the call is repeated.
    expect(cancel).toHaveBeenCalledTimes(2);
  });

  it.each([401, 403, 404, 422])("treats %i as the answer and does not retry", async (status) => {
    const { getOpportunity, ApiError } = await loadApi(10_000);
    fetchMock.mockResolvedValue(jsonResponse({ detail: "no" }, status));

    await expect(getOpportunity("ABCD2345")).rejects.toMatchObject({ status });
    await expect(getOpportunity("ABCD2345")).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(2); // one per call, never a retry
  });

  it("does not repeat a request that already spent the timeout", async () => {
    const { getMasters } = await loadApi(10_000);
    fetchMock.mockRejectedValue(abortError());

    await expect(getMasters()).rejects.toThrow("aborted");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not repeat a request whose body was not JSON", async () => {
    const { getMasters } = await loadApi(10_000);
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => { throw new SyntaxError("Unexpected token <"); },
    } as unknown as Response);

    await expect(getMasters()).rejects.toBeInstanceOf(SyntaxError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not retry when too little budget is left for it to finish", async () => {
    // Enough to wait, not enough for the retry to be worth more than the error.
    const { getMasters } = await loadApi(250);
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));

    await expect(getMasters()).rejects.toThrow("fetch failed");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not retry when the wait itself used up the budget", async () => {
    const { getMasters } = await loadApi(1_000);
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    // Congest the event loop the way a burst of parallel renders does, so the
    // backoff overruns and the retry would start with nothing left to spend.
    setTimeout(() => {
      const until = Date.now() + 900;
      while (Date.now() < until) { /* hold the loop */ }
    }, 0);

    await expect(getMasters()).rejects.toThrow("fetch failed");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("spends the configured timeout on the whole call, not on each attempt", async () => {
    const budgetMs = 1000;
    const firstAttemptMs = 300;
    const { getMasters } = await loadApi(budgetMs);
    let secondAttemptStartedAt = 0;
    fetchMock
      .mockImplementationOnce(async () => {
        await new Promise((resolve) => setTimeout(resolve, firstAttemptMs));
        throw new TypeError("fetch failed");
      })
      .mockImplementationOnce((_url: string, init: { signal: AbortSignal }) => {
        secondAttemptStartedAt = Date.now();
        return hangsUntilAborted(init);
      });

    const startedAt = Date.now();
    await expect(getMasters()).rejects.toThrow("aborted");
    const finishedAt = Date.now();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    // The retry inherits what is left of the budget, not a second full one.
    expect(finishedAt - secondAttemptStartedAt).toBeLessThan(budgetMs - firstAttemptMs);
    expect(finishedAt - startedAt).toBeLessThan(budgetMs + 200);
  });

  it("waits before retrying so parallel reads do not repeat in one burst", async () => {
    const { getMasters } = await loadApi(10_000);
    const calledAt: number[] = [];
    fetchMock.mockImplementation(async () => {
      calledAt.push(Date.now());
      throw new TypeError("fetch failed");
    });

    await expect(getMasters()).rejects.toThrow("fetch failed");
    expect(calledAt).toHaveLength(2);
    expect(calledAt[1] - calledAt[0]).toBeGreaterThanOrEqual(90);
  });

  it("does not retry the site-wide fan-out the sitemap uses", async () => {
    const { getAllOpportunities } = await loadApi(10_000);
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));

    await expect(getAllOpportunities()).rejects.toThrow("fetch failed");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("issues one request per page for the fan-out, with no retries", async () => {
    const { getAllOpportunities } = await loadApi(10_000);
    fetchMock.mockImplementation(async (url: string) => jsonResponse({
      items: [{ id: url }], total: 3, page: 1, per_page: 100, total_pages: 3,
    }));

    const items = await getAllOpportunities();
    expect(items).toHaveLength(3);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("sends the internal token as a header and never in the URL", async () => {
    const { getCompany } = await loadApi(10_000);
    fetchMock.mockResolvedValue(jsonResponse({ public_code: "CMPNY001" }));

    await getCompany("CMPNY001");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/api/v1/companies/CMPNY001");
    expect(init.headers["X-Internal-API-Token"]).toBe("test-token");
  });

  it("refuses to substitute the published development token in production", async () => {
    const { getMasters } = await loadApiWithoutToken("production");
    await expect(getMasters()).rejects.toThrow(/API_INTERNAL_TOKEN must be set/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps using the development token default outside production", async () => {
    const { getMasters } = await loadApiWithoutToken("test");
    fetchMock.mockResolvedValue(jsonResponse({ industries: [] }));
    await getMasters();
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers["X-Internal-API-Token"]).toBe("local-development-internal-token");
  });

  it("bounds the site-wide fan-out to a fixed number of concurrent requests", async () => {
    const { getAllOpportunities } = await loadApi(10_000);
    let active = 0;
    let maxActive = 0;
    fetchMock.mockImplementation(async (url: string) => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active -= 1;
      return jsonResponse({ items: [{ id: url }], total: 9, page: 1, per_page: 100, total_pages: 9 });
    });

    const items = await getAllOpportunities();
    expect(items).toHaveLength(9);
    expect(fetchMock).toHaveBeenCalledTimes(9);
    // 8 remaining pages fetched 6-at-a-time: the peak is the bound, not the total.
    expect(maxActive).toBe(6);
  });
});

describe("listing query normalization", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    fetchMock.mockReset();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("drops a search term over the API's 100-character limit instead of forwarding it", async () => {
    const { listingApiParams } = await loadApi(10_000);
    const overLong = "あ".repeat(101);
    expect(listingApiParams({ q: overLong }).q).toHaveLength(100);
    expect(listingApiParams({ q: "普通の検索" }).q).toBe("普通の検索");
  });

  it("drops a sort value the API does not accept", async () => {
    const { listingApiParams } = await loadApi(10_000);
    expect(listingApiParams({ sort: "new" }).sort).toBeUndefined();
    expect(listingApiParams({ sort: "deadline" }).sort).toBe("deadline");
  });

  it("drops a page value that is not a positive integer", async () => {
    const { listingApiParams } = await loadApi(10_000);
    expect(listingApiParams({ page: "0" }).page).toBeUndefined();
    expect(listingApiParams({ page: "abc" }).page).toBeUndefined();
    expect(listingApiParams({ page: "1.5" }).page).toBeUndefined();
    expect(listingApiParams({ page: "+1" }).page).toBeUndefined();
    expect(listingApiParams({ page: "3" }).page).toBe("3");
  });

  it("never forwards an invalid q, sort, or page to the internal API", async () => {
    const { getOpportunities } = await loadApi(10_000);
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0, page: 1, per_page: 12, total_pages: 0 }));

    await getOpportunities({ q: "x".repeat(150), sort: "new", page: "0" });
    const [url] = fetchMock.mock.calls[0];
    const requested = new URL(url);
    expect(requested.searchParams.get("q")).toHaveLength(100);
    expect(requested.searchParams.has("sort")).toBe(false);
    expect(requested.searchParams.has("page")).toBe(false);
  });

  it("forwards a valid q, sort, and page untouched", async () => {
    const { getOpportunities } = await loadApi(10_000);
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0, page: 2, per_page: 12, total_pages: 5 }));

    await getOpportunities({ q: "エンジニア", sort: "updated", page: "2" });
    const [url] = fetchMock.mock.calls[0];
    const requested = new URL(url);
    expect(requested.searchParams.get("q")).toBe("エンジニア");
    expect(requested.searchParams.get("sort")).toBe("updated");
    expect(requested.searchParams.get("page")).toBe("2");
  });
});
