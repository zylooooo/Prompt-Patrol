import ResultPanel from "../ResultPanel";
import { ApiError } from "../../api/client";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

/**
 * A failed check used to read the same sentence whatever went wrong. The
 * detector timing out and the detector being down are different waits, and
 * telling someone to retry immediately after a 10s timeout wastes their time.
 */

afterEach(cleanup);

const alertText = () => screen.getByRole("alert").textContent ?? "";

describe("ResultPanel — failure wording", () => {
  it("names a detector timeout", () => {
    render(
      <ResultPanel
        status="error"
        error={
          new ApiError(
            504,
            "Detector exceeded the 10s budget.",
            "detector_timeout",
          )
        }
      />,
    );
    expect(alertText()).toContain("took too long");
  });

  it("names a detector outage", () => {
    render(
      <ResultPanel
        status="error"
        error={
          new ApiError(503, "temporarily unavailable", "detector_unavailable")
        }
      />,
    );
    expect(alertText()).toContain("temporarily unavailable");
  });

  it("passes through a client-side refusal, which is already written for this screen", () => {
    render(
      <ResultPanel
        status="error"
        error={new ApiError(400, "Enter at least 10 characters.")}
      />,
    );
    expect(alertText()).toContain("Enter at least 10 characters.");
  });

  it("keeps the generic line for a server error, rather than leaking internal wording", () => {
    render(
      <ResultPanel
        status="error"
        error={new ApiError(500, "IntegrityError on relation checks")}
      />,
    );
    expect(alertText()).toContain("The check failed");
    expect(alertText()).not.toContain("IntegrityError");
  });

  it("keeps the generic line when there is no error object at all", () => {
    render(<ResultPanel status="error" />);
    expect(alertText()).toContain("The check failed");
  });

  it("says nothing about failure when a check succeeded", () => {
    render(<ResultPanel status="idle" />);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
