import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import ErrorState from "../ErrorState";

/**
 * Replaces the hand-rolled failure block that used to live in
 * TeachingAssistantsPage. The retry affordance is the point: an error state
 * without a way out is just a dead end.
 */

afterEach(cleanup);

describe("ErrorState", () => {
  it("announces itself so a screen reader hears the failure", () => {
    render(<ErrorState title="Could not load your list" />);

    expect(screen.getByRole("alert").textContent).toContain(
      "Could not load your list",
    );
  });

  it("renders the description when one is given", () => {
    render(<ErrorState title="Nope" description="Nothing has changed." />);

    expect(screen.getByText("Nothing has changed.")).toBeDefined();
  });

  it("offers no retry button when there is nothing to retry", () => {
    render(<ErrorState title="Nope" />);

    expect(screen.queryByRole("button")).toBeNull();
  });

  it("calls onRetry when the user asks to try again", async () => {
    const onRetry = vi.fn();
    render(<ErrorState title="Nope" onRetry={onRetry} />);

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("takes a custom retry label", () => {
    render(<ErrorState title="Nope" onRetry={() => {}} retryLabel="Reload" />);

    expect(screen.getByRole("button", { name: "Reload" })).toBeDefined();
  });

  it("owns the viewport at page size and not at card size", () => {
    const { rerender } = render(<ErrorState title="Nope" size="page" />);
    expect(screen.getByRole("alert").className).toContain("min-h-screen");

    rerender(<ErrorState title="Nope" size="card" />);
    expect(screen.getByRole("alert").className).not.toContain("min-h-screen");
  });

  it("keeps caller layout classes alongside its own", () => {
    render(<ErrorState title="Nope" className="mt-6" />);

    expect(screen.getByRole("alert").className).toContain("mt-6");
  });
});
