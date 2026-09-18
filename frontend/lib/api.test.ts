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
});
