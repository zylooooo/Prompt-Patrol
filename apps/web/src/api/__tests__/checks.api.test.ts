import { checkAnswer, getCapabilities, hasScreeningAccess } from "../checks";
import type { User } from "../auth";
import { ApiError } from "../client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The seam between what the API sends and the shape the screens read. The
 * failure modes here are quiet ones: strictness arrives as objects rather than
 * names, a field arrives under a different name and renders blank, or a check
 * succeeds against the server but never reaches the History page.
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

const INSTRUCTOR: User = {
  email: "teach@smu.edu.sg",
  role: "instructor",
  provisionedBy: null,
};

const ANSWER =
  "Equilibrium price rises because demand shifts outward while supply is fixed.";

// Captured from a real `POST /api/checks` against the running API on
// 2026-08-18, with the ids and text swapped for readable ones. `spans` is in
// here on purpose: the server sends it, this build has no field for it, and the
// mapper must ignore it rather than choke.
const CHECK = {
  check_id: "check-1",
  actor_id: "actor-1",
  batch_id: null,
  external_ref: null,
  verdict: "ai_generated",
  raw_score: 0.81,
  confidence: null,
  abstain_reason: null,
  truncated: false,
  detector: {
    model_version: "roberta-base-openai-detector-v0",
    calibration_version: null,
    strictness_applied: "strict",
    threshold_applied: 0.65,
    target_fpr: 0.001,
    used_question_text: false,
  },
  answer_text: ANSWER,
  question_text: null,
  explanation: null,
  spans: null,
  created_at: "2026-08-17T19:26:53.406348+00:00",
  latency_ms: 87,
};

const bodyOf = (mock: ReturnType<typeof route>) =>
  JSON.parse(mock.mock.calls[0][1]?.body as string) as Record<string, unknown>;

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

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

describe("checkAnswer", () => {
  it("posts to the checks endpoint", async () => {
    const mock = route(() => CHECK);

    await checkAnswer(INSTRUCTOR, { answerText: ANSWER });

    expect(mock.mock.calls[0][0]).toBe("/api/checks");
    expect(mock.mock.calls[0][1]).toMatchObject({ method: "POST" });
  });

  it("sends exactly the keys the request model allows", async () => {
    // CheckCreateRequest is `extra="forbid"`. An extra key, or a camelCase one,
    // is a 422 the screen has no sentence for.
    const mock = route(() => CHECK);

    await checkAnswer(INSTRUCTOR, {
      answerText: `  ${ANSWER}  `,
      questionText: "  Explain equilibrium price.  ",
      externalRef: " ECON101-Q3 ",
      strictness: "strict",
      retainAnswer: false,
    });

    // batch_id/batch_file_name are gone from CheckCreateRequest as of
    // openapi.yaml [0.13.0] - only the Worker may set a check's batch_id now,
    // so a single check must not send them at all (extra="forbid" 422s on it).
    expect(bodyOf(mock)).toEqual({
      answer_text: ANSWER,
      question_text: "Explain equilibrium price.",
      external_ref: "ECON101-Q3",
      strictness: "strict",
      retain_answer: false,
    });
  });

  it("defaults strictness and retention the way the form does", async () => {
    const mock = route(() => CHECK);

    await checkAnswer(INSTRUCTOR, { answerText: ANSWER });

    expect(bodyOf(mock)).toMatchObject({
      strictness: "standard",
      retain_answer: true,
      question_text: null,
      external_ref: null,
    });
  });

  it("reads the server's field names onto the ones the screens use", async () => {
    route(() => CHECK);

    const entry = await checkAnswer(INSTRUCTOR, { answerText: ANSWER });

    expect(entry).toEqual({
      kind: "single",
      checkId: "check-1",
      actorId: "actor-1",
      batchId: null,
      externalRef: null,
      verdict: "ai_generated",
      rawScore: 0.81,
      confidence: null,
      abstainReason: null,
      truncated: false,
      detector: {
        modelVersion: "roberta-base-openai-detector-v0",
        calibrationVersion: null,
        strictnessApplied: "strict",
        thresholdApplied: 0.65,
        targetFpr: 0.001,
        usedQuestionText: false,
      },
      answerText: ANSWER,
      questionText: null,
      explanation: null,
      createdAt: "2026-08-17T19:26:53.406348+00:00",
      latencyMs: 87,
    });
  });

  // Asserted against the stored history rather than `stub.listHistory`, which
  // seeds demo rows on first call and filters by owner — neither of which is
  // what this needs to know. The question is only whether the result was
  // written, because that write is what the History page reads.
  const storedHistory = () =>
    JSON.parse(localStorage.getItem("pp.history.v2") ?? "[]") as {
      checkId?: string;
    }[];

  it("writes nothing to localStorage — the server stores the check now", async () => {
    // Until 2026-08-18 this mirrored every result into `pp.history.v2` because
    // the server computed and forgot. It persists now, so a local copy would be
    // a second, diverging record of the same screening.
    route(() => CHECK);

    await checkAnswer(INSTRUCTOR, { answerText: ANSWER });

    expect(storedHistory().some((e) => e.checkId === "check-1")).toBe(false);
  });

  it("does not record anything when the detector fails", async () => {
    route(
      () => ({
        error: "detector_unavailable",
        message: "The detector is temporarily unavailable.",
        request_id: "req-1",
      }),
      503,
    );

    // Not "history is empty" — resolving the actor seeds demo rows on the way
    // through, as it always has. The claim is narrower and is the one that
    // matters: the check that failed is not in there.
    await expect(
      checkAnswer(INSTRUCTOR, { answerText: ANSWER }),
    ).rejects.toBeInstanceOf(ApiError);

    expect(storedHistory().some((e) => e.checkId === "check-1")).toBe(false);
  });

  it("carries the server's failure code so the panel can name it", async () => {
    route(
      () => ({
        error: "detector_timeout",
        message: "Detector exceeded the 10s budget.",
        request_id: "req-2",
      }),
      504,
    );

    await expect(
      checkAnswer(INSTRUCTOR, { answerText: ANSWER }),
    ).rejects.toMatchObject({ code: "detector_timeout", status: 504 });
  });

  it("refuses a too-short answer without asking the server", async () => {
    const mock = route(() => CHECK);

    await expect(
      checkAnswer(INSTRUCTOR, { answerText: "short" }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(mock).not.toHaveBeenCalled();
  });

  it("falls back to uncertain for a verdict this build cannot name", async () => {
    // A detector deployed ahead of the SPA. Claiming "likely AI" from a value we
    // could not read is the one direction a screening tool must not fail in.
    route(() => ({ ...CHECK, verdict: "probably_ai_ish" }));

    const entry = await checkAnswer(INSTRUCTOR, { answerText: ANSWER });

    expect(entry.verdict).toBe("uncertain");
  });

  it("drops explanation cues it has no wording for", async () => {
    route(() => ({
      ...CHECK,
      explanation: { cues: ["formal_vocabulary", "quantum_entanglement"] },
    }));

    const entry = await checkAnswer(INSTRUCTOR, { answerText: ANSWER });

    expect(entry.explanation).toEqual({ cues: ["formal_vocabulary"] });
  });
});

describe("hasScreeningAccess", () => {
  // The gate used to answer from a localStorage table of fabricated accounts, so
  // a real teaching assistant matched nothing and every screening screen told
  // them they had no instructor. It reads the session payload now.
  const ta = (provisionedBy: string | null): User => ({
    email: "ta@smu.edu.sg",
    role: "teaching_assistant",
    provisionedBy,
  });

  it("lets a teaching assistant with a provisioner screen", () => {
    expect(hasScreeningAccess(ta("instructor-1"))).toBe(true);
  });

  it("holds back a teaching assistant nobody provisioned", () => {
    expect(hasScreeningAccess(ta(null))).toBe(false);
  });

  it("never holds back an instructor or an admin", () => {
    expect(hasScreeningAccess(INSTRUCTOR)).toBe(true);
    expect(
      hasScreeningAccess({
        email: "admin@smu.edu.sg",
        role: "root_admin",
        provisionedBy: null,
      }),
    ).toBe(true);
  });

  it("answers from the session, not from anything this browser stored", () => {
    localStorage.clear();

    expect(hasScreeningAccess(ta("instructor-1"))).toBe(true);
  });

  it("refuses a single check without reaching the server", async () => {
    const mock = route(() => CHECK, 201);

    await expect(
      checkAnswer(ta(null), { answerText: ANSWER }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(mock).not.toHaveBeenCalled();
  });

});
