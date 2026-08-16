import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import UnassignedNotice from "../UnassignedNotice";

/**
 * A newly provisioned TA can reach both nav destinations and use neither. The
 * wording is shared rather than repeated so the two pages cannot drift into
 * describing what is one blocker as two different problems.
 */

afterEach(cleanup);

describe("UnassignedNotice", () => {
  it("names the blocker and who resolves it", () => {
    render(<UnassignedNotice />);

    expect(
      screen.getByText("You are not assigned to an instructor yet"),
    ).toBeDefined();
    expect(screen.getByText(/Ask them to add you/)).toBeDefined();
  });

  it("is not announced as an error", () => {
    // Nothing has failed - this is the account's normal starting state, and
    // role="alert" would interrupt a screen reader to say so.
    render(<UnassignedNotice />);

    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps caller layout classes", () => {
    const { container } = render(<UnassignedNotice className="mt-8" />);

    expect(container.querySelector("section")?.className).toContain("mt-8");
  });
});
