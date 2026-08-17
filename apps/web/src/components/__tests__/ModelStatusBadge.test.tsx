import ModelStatusBadge from "../ModelStatusBadge";
import { renderWithProviders } from "../../test/render";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";

/**
 * The badge is the first thing wired to the detector, so it is also the first
 * thing that can be broken by the detector being down. It must degrade to what
 * it said before this was wired at all, never to a blank or a guess.
 */

const CAPABILITIES = {
  model_version: "roberta-base-openai-detector-v0",
  requires_question_text: false,
  min_answer_chars: 10,
  max_answer_chars: 10000,
  strictness_levels: [{ level: "standard", target_fpr: 0.01 }],
  supports_explanation: false,
  supports_spans: false,
};

const FALLBACK = "demo detector · scores uncalibrated";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ModelStatusBadge", () => {
  it("names the model once the detector answers", async () => {
    vi.stubGlobal("fetch", () =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(CAPABILITIES),
      }),
    );

    renderWithProviders(<ModelStatusBadge />);

    await waitFor(() =>
      expect(screen.getByText(/roberta-base-openai-detector-v0/)).toBeDefined(),
    );
  });

  it("keeps the old wording while the answer is still in flight", () => {
    vi.stubGlobal("fetch", () => new Promise(() => {}));

    renderWithProviders(<ModelStatusBadge />);

    expect(screen.getByText(FALLBACK)).toBeDefined();
  });

  it("keeps the old wording when the detector cannot be reached", async () => {
    // A dead detector is not a reason to blank the badge or claim a version.
    vi.stubGlobal("fetch", () => Promise.reject(new Error("network down")));

    renderWithProviders(<ModelStatusBadge />);

    await waitFor(() => expect(screen.getByText(FALLBACK)).toBeDefined());
  });
});
