import ErrorBoundary from "../ErrorBoundary";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * What this replaces: nothing caught a render error, so React unmounted the
 * whole tree and left a blank white page. To the person looking at it that is
 * indistinguishable from the app failing to load, and the reason was only ever
 * in the console.
 */

function Throws(): never {
  throw new Error("kaboom");
}

beforeEach(() => {
  // React logs the caught error itself, on top of our own handler. Both are
  // expected here and would otherwise bury the real output.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

describe("ErrorBoundary", () => {
  it("shows something instead of a blank page when a child throws", () => {
    render(
      <ErrorBoundary>
        <Throws />
      </ErrorBoundary>,
    );

    expect(screen.getByText("Something went wrong")).toBeDefined();
  });

  it("offers a way out", () => {
    render(
      <ErrorBoundary>
        <Throws />
      </ErrorBoundary>,
    );

    expect(
      screen.getByRole("button", { name: "Reload the page" }),
    ).toBeDefined();
  });

  it("announces itself, so it is not a silent swap", () => {
    render(
      <ErrorBoundary>
        <Throws />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toBeDefined();
  });

  it("keeps the reason in the console for whoever has to diagnose it", () => {
    render(
      <ErrorBoundary>
        <Throws />
      </ErrorBoundary>,
    );

    expect(console.error).toHaveBeenCalledWith(
      "Unhandled render error:",
      expect.objectContaining({ message: "kaboom" }),
      expect.anything(),
    );
  });

  it("stays out of the way when nothing throws", () => {
    render(
      <ErrorBoundary>
        <p>Ordinary page</p>
      </ErrorBoundary>,
    );

    expect(screen.getByText("Ordinary page")).toBeDefined();
    expect(screen.queryByText("Something went wrong")).toBeNull();
  });
});
