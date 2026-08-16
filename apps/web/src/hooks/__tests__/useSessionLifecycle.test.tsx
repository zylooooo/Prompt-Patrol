import type { SessionInfo } from "../../api/auth";
import { act, renderHook } from "@testing-library/react";
import { useSessionLifecycle } from "../useSessionLifecycle";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The bug being guarded: the idle window only slides when a request reaches
 * the API, and working inside the SPA sends none - screening and history run
 * off localStorage. Someone at their desk therefore looked identical to
 * someone who had left, and got evicted for inactivity mid-sentence.
 *
 * So the cases that matter are the two that used to be indistinguishable:
 * present-but-quiet must renew, and actually-absent must still expire.
 */

const MINUTE = 60_000;

function session(overrides: Partial<SessionInfo> = {}): SessionInfo {
  return {
    expiresAt: Date.now() + 90 * MINUTE,
    capped: false,
    idleTimeoutSeconds: 5400,
    ...overrides,
  };
}

// Stands in for a person doing something deliberate.
function interact() {
  act(() => {
    window.dispatchEvent(new Event("keydown"));
  });
}

function setup(
  info: SessionInfo | null,
  onRenew = vi.fn(),
  onExpired = vi.fn(),
) {
  onRenew.mockResolvedValue(session());
  const view = renderHook(() =>
    useSessionLifecycle({ session: info, onRenew, onExpired }),
  );
  return { ...view, onRenew, onExpired };
}

const tick = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useSessionLifecycle — keeping a working user signed in", () => {
  it("renews for someone who is present when the deadline is close", async () => {
    const { onRenew } = setup(session({ expiresAt: Date.now() + 4 * MINUTE }));
    interact();

    await tick(1_000);

    expect(onRenew).toHaveBeenCalled();
  });

  it("does not renew while the deadline is far away", async () => {
    const { onRenew } = setup(session({ expiresAt: Date.now() + 60 * MINUTE }));
    interact();

    await tick(5_000);

    expect(onRenew).not.toHaveBeenCalled();
  });

  it("never renews a session held open by the 12-hour cap", async () => {
    // The cap does not move, so a request would spend a round trip to learn
    // nothing and would still not save the session.
    const { onRenew } = setup(
      session({ expiresAt: Date.now() + 3 * MINUTE, capped: true }),
    );
    interact();

    await tick(2_000);

    expect(onRenew).not.toHaveBeenCalled();
  });

  it("counts opening the app as activity", async () => {
    // Someone who lands on a page with four minutes left has just done
    // something, and holding that against them would sign them out for
    // inactivity moments after they arrived.
    const { onRenew } = setup(session({ expiresAt: Date.now() + 4 * MINUTE }));

    await tick(1_000);

    expect(onRenew).toHaveBeenCalled();
  });

  it("stops treating an old interaction as presence", async () => {
    // The other half of the contract. If mere elapsed time renewed the
    // session, the idle timeout would not exist.
    const { onRenew } = setup(session({ expiresAt: Date.now() + 60 * MINUTE }));
    interact();

    // Past the activity window, then into renewal range.
    await tick(56 * MINUTE);

    expect(onRenew).not.toHaveBeenCalled();
  });
});

describe("useSessionLifecycle — warning before eviction", () => {
  it("warns an absent user with a live countdown", async () => {
    // Eight minutes out, so mounting does not sit inside the renewal window
    // and the only thing under test is the passage of time.
    const { result } = setup(session({ expiresAt: Date.now() + 8 * MINUTE }));

    await tick(1_000);
    expect(result.current.phase).toBe("ok");

    await tick(6 * MINUTE);
    expect(result.current.phase).toBe("warning");
    expect(result.current.secondsRemaining).toBeLessThanOrEqual(120);
    expect(result.current.secondsRemaining).toBeGreaterThan(100);

    await tick(30_000);
    expect(result.current.secondsRemaining).toBeLessThanOrEqual(90);
  });

  it("never shows the warning to someone who is working", async () => {
    // The dialog is for people who left. Interrupting someone mid-read to ask
    // whether they are still there is the failure this whole hook exists to
    // remove.
    const { result, onRenew } = setup(
      session({ expiresAt: Date.now() + 4 * MINUTE }),
    );
    interact();

    await tick(1_000);

    expect(onRenew).toHaveBeenCalled();
    expect(result.current.phase).toBe("ok");
  });

  it("renews on an explicit 'stay signed in' even with no recent activity", async () => {
    const { result, onRenew } = setup(
      session({ expiresAt: Date.now() + 60_000 }),
    );
    await tick(1_000);
    expect(result.current.phase).toBe("warning");

    await act(async () => {
      result.current.staySignedIn();
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(onRenew).toHaveBeenCalled();
  });

  it("keeps a dismissed warning dismissed", async () => {
    const { result } = setup(session({ expiresAt: Date.now() + 60_000 }));
    await tick(1_000);

    act(() => result.current.dismissWarning());
    await tick(5_000);

    expect(result.current.phase).toBe("ok");
  });
});

describe("useSessionLifecycle — the end", () => {
  it("reports expiry once the deadline passes", async () => {
    const { onExpired } = setup(session({ expiresAt: Date.now() + 2_000 }));

    await tick(3_000);

    expect(onExpired).toHaveBeenCalledWith(false);
  });

  it("says which limit ran out so the user can be told", async () => {
    const { onExpired } = setup(
      session({ expiresAt: Date.now() + 2_000, capped: true }),
    );

    await tick(3_000);

    expect(onExpired).toHaveBeenCalledWith(true);
  });

  it("does nothing at all without a session", async () => {
    const { result, onRenew, onExpired } = setup(null);

    await tick(10 * MINUTE);

    expect(result.current.phase).toBe("ok");
    expect(onRenew).not.toHaveBeenCalled();
    expect(onExpired).not.toHaveBeenCalled();
  });

  it("does not hammer a failing renewal every second", async () => {
    // A dead network must not turn the last five minutes of a session into
    // three hundred requests.
    const failing = vi.fn().mockRejectedValue(new Error("offline"));
    setup(session({ expiresAt: Date.now() + 4 * MINUTE }), failing);

    for (let i = 0; i < 10; i += 1) {
      interact();
      await tick(1_000);
    }

    expect(failing.mock.calls.length).toBeLessThanOrEqual(2);
  });
});

describe("useSessionLifecycle — a shorter idle window on the server", () => {
  it("scales the renewal band so it cannot swallow the whole window", async () => {
    // The server owns SESSION_IDLE_TTL. Cutting it to three minutes must not
    // leave the fixed five-minute renewal band covering the entire window,
    // which would renew on every tick and disable the idle timeout outright.
    const { onRenew } = setup(
      session({ expiresAt: Date.now() + 2 * MINUTE, idleTimeoutSeconds: 180 }),
    );
    interact();

    await tick(2_000);

    expect(onRenew).not.toHaveBeenCalled();
  });

  it("still renews once inside the scaled band", async () => {
    // A quarter of three minutes is 45 seconds.
    const { onRenew } = setup(
      session({ expiresAt: Date.now() + 30_000, idleTimeoutSeconds: 180 }),
    );
    interact();

    await tick(1_000);

    expect(onRenew).toHaveBeenCalled();
  });

  it("scales the warning band with it", async () => {
    // A tenth of three minutes is 18 seconds, so at 30s left there is no
    // warning yet - the fixed two-minute band would have fired immediately.
    const { result } = setup(
      session({ expiresAt: Date.now() + 30_000, idleTimeoutSeconds: 180 }),
    );

    await tick(2_000);

    expect(result.current.phase).toBe("ok");
  });
});

describe("useSessionLifecycle — not hammering the server at the deadline", () => {
  it("reports expiry once, not once per tick", async () => {
    // The interval keeps running past the deadline and the callback issues a
    // request. Observed live as a burst of twenty requests in one second.
    const { onExpired } = setup(session({ expiresAt: Date.now() + 1_000 }));

    await tick(30_000);

    expect(onExpired).toHaveBeenCalledTimes(1);
  });
});
