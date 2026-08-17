import { ApiError } from "../client";
import { getCapabilities } from "../checks";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * The seam between the detector's capability document and the shape the screens
 * read. The failure mode here is quiet: strictness arrives as objects rather
 * than names, so a mapping slip renders an empty picker instead of throwing.
 */

const CAPABILITIES = {
  model_version: "roberta-base-openai-detector-v0",
  requires_question_text: false,
  min_answer_chars: 10,
  max_answer_chars: 10000,
  max_tokens_scored: 512,
  strictness_levels: [
    { level: "lenient", target_fpr: 0.05 },
    { level: "standard", target_fpr: 0.01 },
    { level: "strict", target_fpr: 0.001 },
  ],
  calibration_version: null,
  supports_confidence: false,
  supports_explanation: false,
  supports_spans: false,
};

/** Answers each call from `handler`, keyed off the requested path. */
function route(
  handler: (url: string, init?: RequestInit) => unknown,
  status = 200,
) {
  const mock = vi.fn((url: string, init?: RequestInit) =>
    Promise.resolve({
      ok: status < 400,
      status,
      json: () => Promise.resolve(handler(url, init)),
    }),
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => vi.unstubAllGlobals());

describe("getCapabilities", () => {
  it("reads the server's field names onto the ones the screens use", async () => {
    route(() => CAPABILITIES);

    expect(await getCapabilities()).toEqual({
      modelVersion: "roberta-base-openai-detector-v0",
      requiresQuestionText: false,
      minAnswerChars: 10,
      maxAnswerChars: 10000,
      strictnessLevels: ["lenient", "standard", "strict"],
      supportsExplanation: false,
      supportsSpans: false,
    });
  });

  it("asks the detector endpoint", async () => {
    const mock = route(() => CAPABILITIES);

    await getCapabilities();

    expect(mock.mock.calls[0][0]).toBe("/api/detector");
  });

  it("flattens each strictness level to its name", async () => {
    // The server sends {level, target_fpr}; the screens index STRICTNESS_TEXT by
    // the bare name. Passing the objects through renders every option blank.
    route(() => CAPABILITIES);

    const { strictnessLevels } = await getCapabilities();

    expect(strictnessLevels.every((level) => typeof level === "string")).toBe(
      true,
    );
  });

  it("drops a level this build has no copy for", async () => {
    // A detector deployed ahead of the SPA can offer a level the UI cannot name.
    // Dropping it costs one option; keeping it renders a blank one.
    route(() => ({
      ...CAPABILITIES,
      strictness_levels: [
        { level: "standard", target_fpr: 0.01 },
        { level: "paranoid", target_fpr: 0.0001 },
      ],
    }));

    const { strictnessLevels } = await getCapabilities();

    expect(strictnessLevels).toEqual(["standard"]);
  });

  it("raises rather than inventing a capability document", async () => {
    // The badge decides what to show from whether this resolved. Returning a
    // default here would state a model version nobody served.
    route(() => ({ detail: "Insufficient role" }), 403);

    await expect(getCapabilities()).rejects.toBeInstanceOf(ApiError);
  });
});
