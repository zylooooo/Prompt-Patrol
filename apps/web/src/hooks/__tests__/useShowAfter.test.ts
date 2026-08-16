import { useShowAfter } from "../useShowAfter";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

const advance = (ms: number) => act(() => void vi.advanceTimersByTime(ms));

describe("useShowAfter", () => {
  it("is false immediately", () => {
    const { result } = renderHook(() => useShowAfter(true, 250));

    expect(result.current).toBe(false);
  });

  it("is still false one tick before the delay", () => {
    const { result } = renderHook(() => useShowAfter(true, 250));

    advance(249);

    expect(result.current).toBe(false);
  });

  it("becomes true once the delay elapses", () => {
    const { result } = renderHook(() => useShowAfter(true, 250));

    advance(250);

    expect(result.current).toBe(true);
  });

  it("stays false when the wait ends before the delay", () => {
    const { result, rerender } = renderHook(
      ({ active }) => useShowAfter(active, 250),
      { initialProps: { active: true } },
    );

    advance(100);
    rerender({ active: false });
    advance(1000);

    expect(result.current).toBe(false);
  });

  it("does not carry a stale true into the next wait", () => {
    // Otherwise the second slow check paints its spinner instantly, which is
    // the flicker this hook exists to prevent.
    const { result, rerender } = renderHook(
      ({ active }) => useShowAfter(active, 250),
      { initialProps: { active: true } },
    );
    advance(250);
    expect(result.current).toBe(true);

    rerender({ active: false });
    expect(result.current).toBe(false);

    rerender({ active: true });
    expect(result.current).toBe(false);

    advance(250);
    expect(result.current).toBe(true);
  });

  it("never reports true while inactive, however long it waits", () => {
    const { result } = renderHook(() => useShowAfter(false, 250));

    advance(10_000);

    expect(result.current).toBe(false);
  });
});
