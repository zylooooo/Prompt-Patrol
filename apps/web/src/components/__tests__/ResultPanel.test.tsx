import ResultPanel from "../ResultPanel";
import { ApiError } from "../../api/client";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ResultPanel reads detector capabilities (the strictness flag).
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>
    {children}
  </QueryClientProvider>
);

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
    expect(alertText()).toContain("detector is unavailable");
  });

  it("never shows the server's own message, which isn't in the product voice", () => {
    // Copy is keyed on the stable `error` code; a 400's message is a
    // validation rule like "answer_text: String should have at least 20
    // characters" (PRODUCT.md, Voice and Copy).
    render(
      <ResultPanel
        status="error"
        error={
          new ApiError(
            400,
            "answer_text: String should have at least 20 characters",
            "invalid_request",
          )
        }
      />,
    );
    expect(alertText()).toContain("The check didn't go through");
    expect(alertText()).not.toContain("answer_text");
  });

  it("asks for the question when the detector needs it", () => {
    render(
      <ResultPanel
        status="error"
        error={
          new ApiError(
            400,
            "question_text is required",
            "question_text_required",
          )
        }
      />,
    );
    expect(alertText()).toContain("Add the question");
  });

  it("keeps the generic line for a server error, rather than leaking internal wording", () => {
    render(
      <ResultPanel
        status="error"
        error={new ApiError(500, "IntegrityError on relation checks")}
      />,
    );
    expect(alertText()).toContain("The check didn't go through");
    expect(alertText()).not.toContain("IntegrityError");
  });

  it("keeps the generic line when there is no error object at all", () => {
    render(<ResultPanel status="error" />);
    expect(alertText()).toContain("The check didn't go through");
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
      { wrapper },
    );
    expect(screen.getByText(/aren't calibrated/)).toBeDefined();
    expect(screen.getByText(/aren't evidence of misconduct/)).toBeDefined();
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
      { wrapper },
    );
    expect(screen.queryByText(/aren't calibrated/)).toBeNull();
  });
});
