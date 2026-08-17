import { ApiError, apiRequest, NETWORK_ERROR_STATUS } from "../client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Everything here exists so a caller can tell three things apart that used to
 * collapse into one `Error("Request failed with status 401")`: what the server
 * decided, why it decided it, and whether the server answered at all. The last
 * distinction is the one that matters most - a network failure reported as a
 * sign-out sends a person to a login page served by the same dead backend.
 */

const respondWith = (status: number, body: unknown, ok = false) =>
  vi.fn().mockResolvedValue({
    ok,
    status,
    json: () => Promise.resolve(body),
  });

beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
afterEach(() => vi.unstubAllGlobals());

describe("apiRequest — reading the server's account of a failure", () => {
  it("lifts the code out of a structured FastAPI detail", async () => {
    vi.stubGlobal(
      "fetch",
      respondWith(401, {
        detail: { code: "session_expired", message: "Idle limit passed." },
      }),
    );

    const error = await apiRequest("/api/auth/me").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).code).toBe("session_expired");
    expect((error as ApiError).message).toBe("Idle limit passed.");
  });

  it("reads a plain string detail", async () => {
    vi.stubGlobal("fetch", respondWith(403, { detail: "Insufficient role" }));

    const error = (await apiRequest("/api/users").catch(
      (e: unknown) => e,
    )) as ApiError;

    expect(error.message).toBe("Insufficient role");
    expect(error.code).toBeNull();
  });

  it("reads the flat error shape the checks routes return", async () => {
    // That shape calls its code `error`, not `code`. This test used to assert
    // only the message, so the code arriving as null went unnoticed until the
    // check form needed it to tell a timeout from an outage.
    vi.stubGlobal(
      "fetch",
      respondWith(503, {
        error: "detector_unavailable",
        message: "The detector is temporarily unavailable.",
        request_id: "req-1",
      }),
    );

    const error = (await apiRequest("/api/checks", { method: "POST" }).catch(
      (e: unknown) => e,
    )) as ApiError;

    expect(error.message).toBe("The detector is temporarily unavailable.");
    expect(error.code).toBe("detector_unavailable");
  });

  it("survives a body that is not JSON at all", async () => {
    // An nginx error page or a crashed worker. The status is still the answer.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: () => Promise.reject(new SyntaxError("Unexpected token <")),
      }),
    );

    const error = (await apiRequest("/api/auth/me").catch(
      (e: unknown) => e,
    )) as ApiError;

    expect(error.status).toBe(502);
    expect(error.message).toContain("502");
  });
});

describe("apiRequest — no answer at all", () => {
  it("reports an unreachable server as a network failure, not a rejection", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("failed")));

    const error = (await apiRequest("/api/auth/me").catch(
      (e: unknown) => e,
    )) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(NETWORK_ERROR_STATUS);
    expect(error.isUnreachable).toBe(true);
    // Sorts below the 4xx band, so queryClient retries it instead of taking it
    // as the server's final word.
    expect(error.status).toBeLessThan(400);
  });

  it("keeps a caller's own abort an abort", async () => {
    // TanStack Query cancels superseded and unmounted queries this way and
    // must be able to discard the result silently. Rewriting it as a network
    // failure would surface "we couldn't reach the server" on every navigation.
    const controller = new AbortController();
    const abortError = new DOMException("Aborted", "AbortError");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => {
        controller.abort();
        return Promise.reject(abortError);
      }),
    );

    const error = await apiRequest("/api/auth/me", {
      signal: controller.signal,
    }).catch((e: unknown) => e);

    expect(error).toBe(abortError);
    expect(error).not.toBeInstanceOf(ApiError);
  });

  it("gives up on a server that never answers", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          }),
      ),
    );

    const pending = apiRequest("/api/auth/me", { timeoutMs: 5_000 }).catch(
      (e: unknown) => e,
    );
    await vi.advanceTimersByTimeAsync(5_001);
    const error = (await pending) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.isUnreachable).toBe(true);
    expect(error.message).toContain("too long");
    vi.useRealTimers();
  });
});

describe("apiRequest — success", () => {
  it("returns the parsed body", async () => {
    vi.stubGlobal("fetch", respondWith(200, { email: "ada@smu.edu.sg" }, true));

    await expect(apiRequest("/api/auth/me")).resolves.toEqual({
      email: "ada@smu.edu.sg",
    });
  });

  it("returns nothing for a 204", async () => {
    vi.stubGlobal("fetch", respondWith(204, null, true));

    await expect(
      apiRequest("/api/users/x", { method: "DELETE" }),
    ).resolves.toBe(undefined);
  });

  it("sends the session cookie on every request", async () => {
    // The entire client-side auth story. Dropping it 401s everything.
    const fetchMock = respondWith(200, {}, true);
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/api/auth/me");

    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      credentials: "include",
    });
  });
});

describe("ApiError — telling 'no answer' from 'a bad answer'", () => {
  it("counts a gateway failure as unreachable", () => {
    // Neither proxy in this project forwards a dead backend as a dead socket:
    // Vite and nginx both answer 502. Classifying that as an application error
    // tells the user the server replied when nothing is running at all.
    for (const status of [502, 503, 504]) {
      expect(new ApiError(status, "x").isUnreachable).toBe(true);
    }
  });

  it("does not count an application error as unreachable", () => {
    for (const status of [400, 401, 403, 409, 500]) {
      expect(new ApiError(status, "x").isUnreachable).toBe(false);
    }
  });
});

describe("getSession — asking without keeping the session alive", () => {
  it("probes on a separate path so the read is not counted as activity", async () => {
    // The bug: the SPA's expiry check was an ordinary read, which slid the
    // idle window server-side and handed back a full fresh one. Checking for
    // expiry was what prevented expiry.
    const fetchMock = respondWith(
      200,
      {
        email: "ada@smu.edu.sg",
        role: "instructor",
        session: {
          expires_in_seconds: 90,
          capped: false,
          idle_timeout_seconds: 5400,
        },
      },
      true,
    );
    vi.stubGlobal("fetch", fetchMock);

    const { getSession } = await import("../auth");
    await getSession(undefined, { probe: true });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/auth/me?probe=1");

    await getSession();
    expect(fetchMock.mock.calls[1][0]).toBe("/api/auth/me");
  });
});
