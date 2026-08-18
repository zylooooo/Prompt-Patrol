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

describe("ResultPanel — the demo caveat", () => {
  const detector = {
    modelVersion: "roberta-base-openai-detector-v0",
    calibrationVersion: null as string | null,
    strictnessApplied: "standard" as const,
    thresholdApplied: 0.5,
    targetFpr: 0.01,
    usedQuestionText: false,
  };
  const result = (over: Record<string, unknown> = {}) =>
    ({
      kind: "single",
      checkId: "c1",
      actorId: "a1",
      batchId: null,
      externalRef: null,
      verdict: "ai_generated",
      rawScore: 0.81,
      confidence: null,
      abstainReason: null,
      truncated: false,
      detector,
      answerText: "text",
      questionText: null,
      explanation: null,
      createdAt: "2026-08-18T00:00:00.000Z",
      latencyMs: 10,
      ...over,
    }) as never;

  it("says the score is uncalibrated wherever a score is shown", () => {
    // The model has no separation between human and LLM text. A number that
    // looks authoritative on an integrity screen is the failure to avoid.
    render(
      <ResultPanel status="success" result={result()} showSavedLink={false} />,
    );
    expect(screen.getByText(/uncalibrated/)).toBeDefined();
    expect(screen.getByText(/not evidence of misconduct/)).toBeDefined();
  });

  it("drops the caveat once a calibrated model scores the check", () => {
    // Derived from the check's own detector block, so this happens on its own
    // rather than needing someone to remember to remove it.
    render(
      <ResultPanel
        status="success"
        result={result({ detector: { ...detector, calibrationVersion: "v1" } })}
        showSavedLink={false}
      />,
    );
    expect(screen.queryByText(/uncalibrated/)).toBeNull();
  });
});
