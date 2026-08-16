import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The property that matters is that a tab does not hear itself.
 *
 * BroadcastChannel excludes the posting *object*, not the posting tab, so
 * publishing through a freshly-opened channel delivered every message back to
 * this tab's own subscriber. The "session-ended" round trip then reached
 * `invalidateQueries`, which refetched /api/auth/me the ordinary way and slid
 * the idle window on the session that had just been declared over - the
 * session outlived its own eviction.
 */

class FakeBroadcastChannel {
  static instances: FakeBroadcastChannel[] = [];
  private listeners = new Set<(event: MessageEvent) => void>();
  closed = false;

  readonly name: string;

  constructor(name: string) {
    this.name = name;
    FakeBroadcastChannel.instances.push(this);
  }

  postMessage(data: unknown) {
    for (const other of FakeBroadcastChannel.instances) {
      // The real contract: everyone on the channel except the sender.
      if (other === this || other.closed) continue;
      for (const listener of other.listeners) {
        listener({ data } as MessageEvent);
      }
    }
  }

  addEventListener(_type: "message", listener: (event: MessageEvent) => void) {
    this.listeners.add(listener);
  }

  removeEventListener(
    _type: "message",
    listener: (event: MessageEvent) => void,
  ) {
    this.listeners.delete(listener);
  }

  close() {
    this.closed = true;
    this.listeners.clear();
  }
}

beforeEach(() => {
  FakeBroadcastChannel.instances = [];
  vi.stubGlobal("BroadcastChannel", FakeBroadcastChannel);
  vi.resetModules();
});
afterEach(() => vi.unstubAllGlobals());

describe("authChannel", () => {
  it("does not deliver a tab's own event back to itself", async () => {
    const { publishAuthEvent, subscribeToAuthEvents } =
      await import("../authChannel");
    const heard = vi.fn();
    subscribeToAuthEvents(heard);

    publishAuthEvent({ type: "session-ended" });

    expect(heard).not.toHaveBeenCalled();
  });

  it("uses a single channel per tab", async () => {
    const { publishAuthEvent, subscribeToAuthEvents } =
      await import("../authChannel");
    subscribeToAuthEvents(vi.fn());
    publishAuthEvent({ type: "signed-out" });
    publishAuthEvent({ type: "session-renewed", expiresAt: 1 });

    expect(FakeBroadcastChannel.instances).toHaveLength(1);
  });

  it("delivers events from another tab", async () => {
    const { subscribeToAuthEvents } = await import("../authChannel");
    const heard = vi.fn();
    subscribeToAuthEvents(heard);

    // Stands in for a second tab, which is a separate channel object.
    new FakeBroadcastChannel("pp-auth").postMessage({ type: "signed-out" });

    expect(heard).toHaveBeenCalledWith({ type: "signed-out" });
  });

  it("unsubscribing leaves other subscribers in the tab working", async () => {
    const { subscribeToAuthEvents } = await import("../authChannel");
    const first = vi.fn();
    const second = vi.fn();
    const stop = subscribeToAuthEvents(first);
    subscribeToAuthEvents(second);

    stop();
    new FakeBroadcastChannel("pp-auth").postMessage({ type: "session-ended" });

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledOnce();
  });

  it("is inert where BroadcastChannel does not exist", async () => {
    vi.stubGlobal("BroadcastChannel", undefined);
    vi.resetModules();
    const { publishAuthEvent, subscribeToAuthEvents } =
      await import("../authChannel");

    expect(() => publishAuthEvent({ type: "signed-out" })).not.toThrow();
    expect(() => subscribeToAuthEvents(vi.fn())()).not.toThrow();
  });
});
