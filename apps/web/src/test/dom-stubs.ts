import { vi } from "vitest";

/**
 * jsdom implements neither `ResizeObserver` nor `matchMedia`, and three of the
 * `ui/` primitives read them: `DataTable` (viewport + container queries via
 * `useMediaQuery` / `useNarrowContainer`) and `Tabs` / `SegmentedToggle` (the
 * observer that keeps the sliding indicator aligned).
 *
 * Both stubs are inert. That is deliberate, not a shortcut: jsdom does no
 * layout, so `offsetLeft` and `offsetWidth` are always 0 and the indicator's
 * position is not observable here at all. These tests cover roles, ARIA state
 * and keyboard behaviour; **indicator placement needs a real browser.**
 *
 * Call from `beforeEach` — `restoreMocks` in `vitest.config.ts` clears mock
 * state between tests, so installing once per file is not enough.
 */
export function installDomStubs({ matches = false } = {}) {
  class InertResizeObserver implements ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", InertResizeObserver);

  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}
