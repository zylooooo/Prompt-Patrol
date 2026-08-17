import type { User } from "../auth";
import { ApiError } from "../client";
import { checkAnswer, getCapabilities, runBatch } from "../checks";
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

const INSTRUCTOR: User = { email: "teach@smu.edu.sg", role: "instructor" };

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

    expect(bodyOf(mock)).toEqual({
      answer_text: ANSWER,
      question_text: "Explain equilibrium price.",
      external_ref: "ECON101-Q3",
      strictness: "strict",
      retain_answer: false,
      // A single check belongs to no batch, and says so rather than omitting
      // the keys - the server distinguishes null from absent.
      batch_id: null,
      batch_file_name: null,
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

describe("runBatch", () => {
  const input = (ref: string) => ({
    externalRef: ref,
    answerText: `Answer number ${ref}, long enough to pass validation.`,
  });

  /** Answers every row, failing the refs named in `failing`. */
  function batchRoute(failing: string[] = []) {
    return vi.fn((_url: string, init?: RequestInit) => {
      const body = JSON.parse(init?.body as string) as {
        external_ref: string;
        strictness: string;
      };
      if (failing.includes(body.external_ref)) {
        return Promise.resolve({
          ok: false,
          status: 504,
          json: () =>
            Promise.resolve({
              error: "detector_timeout",
              message: "Detector exceeded the 10s budget.",
              request_id: "req",
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 201,
        json: () =>
          Promise.resolve({
            ...CHECK,
            check_id: `check-${body.external_ref}`,
            external_ref: body.external_ref,
            detector: {
              ...CHECK.detector,
              strictness_applied: body.strictness,
            },
          }),
      });
    });
  }

  it("scores every row through the checks endpoint", async () => {
    const mock = batchRoute();
    vi.stubGlobal("fetch", mock);

    const run = await runBatch(INSTRUCTOR, "answers.csv", [
      input("A"),
      input("B"),
      input("C"),
    ]);

    expect(mock).toHaveBeenCalledTimes(3);
    expect(mock.mock.calls.every((call) => call[0] === "/api/checks")).toBe(
      true,
    );
    expect(run.rows).toHaveLength(3);
  });

  it("applies the run's strictness to every row", async () => {
    const mock = batchRoute();
    vi.stubGlobal("fetch", mock);

    await runBatch(
      INSTRUCTOR,
      "answers.csv",
      [input("A"), input("B")],
      "strict",
    );

    for (const call of mock.mock.calls) {
      const body = JSON.parse(call[1]?.body as string) as {
        strictness: string;
      };
      expect(body.strictness).toBe("strict");
    }
  });

  it("keeps the rows it could score when others fail", async () => {
    // The point of the phase: 2 timeouts must not discard 2 good scores.
    vi.stubGlobal("fetch", batchRoute(["B", "D"]));

    const run = await runBatch(INSTRUCTOR, "answers.csv", [
      input("A"),
      input("B"),
      input("C"),
      input("D"),
    ]);

    expect(run.rows.map((row) => row.externalRef).sort()).toEqual(["A", "C"]);
    expect(run.failures?.map((f) => f.externalRef)).toEqual(["B", "D"]);
  });

  it("names why a row failed", async () => {
    vi.stubGlobal("fetch", batchRoute(["B"]));

    const run = await runBatch(INSTRUCTOR, "answers.csv", [
      input("A"),
      input("B"),
    ]);

    expect(run.failures?.[0].reason).toContain("took too long");
  });

  it("never invents a score for a row that failed", async () => {
    // A row shown as 0.00 "uncertain" would be stating a result nobody
    // produced. Failed rows stay out of `rows` and out of `counts`.
    vi.stubGlobal("fetch", batchRoute(["B"]));

    const run = await runBatch(INSTRUCTOR, "answers.csv", [
      input("A"),
      input("B"),
    ]);

    const total =
      run.counts.ai_generated + run.counts.uncertain + run.counts.human_written;
    expect(total).toBe(run.rows.length);
    expect(run.rows.some((row) => row.externalRef === "B")).toBe(false);
  });

  it("omits the failures field entirely when nothing failed", async () => {
    vi.stubGlobal("fetch", batchRoute());

    const run = await runBatch(INSTRUCTOR, "answers.csv", [input("A")]);

    expect(run.failures).toBeUndefined();
  });

  it("fails the run when no row could be scored", async () => {
    // An empty table under a success banner would report a run that produced
    // nothing as if it had worked.
    vi.stubGlobal("fetch", batchRoute(["A", "B"]));

    await expect(
      runBatch(INSTRUCTOR, "answers.csv", [input("A"), input("B")]),
    ).rejects.toBeInstanceOf(ApiError);
  });

  it("reports progress once per row, including the failures", async () => {
    vi.stubGlobal("fetch", batchRoute(["B"]));
    const seen: number[] = [];

    await runBatch(
      INSTRUCTOR,
      "answers.csv",
      [input("A"), input("B"), input("C")],
      "standard",
      (done, total) => {
        seen.push(done);
        expect(total).toBe(3);
      },
    );

    expect(seen).toHaveLength(3);
    expect(Math.max(...seen)).toBe(3);
  });

  it("tags every row with one batch id and the file name, server-side", async () => {
    // The grouping is the client's to assign - the server has no batch concept
    // - but it is stored, so a reload can reconstruct the run.
    const mock = batchRoute();
    vi.stubGlobal("fetch", mock);

    const run = await runBatch(INSTRUCTOR, "answers.csv", [
      input("A"),
      input("B"),
    ]);

    const bodies = mock.mock.calls.map(
      (call) => JSON.parse(call[1]?.body as string) as Record<string, unknown>,
    );
    expect(new Set(bodies.map((b) => b.batch_id)).size).toBe(1);
    expect(bodies.every((b) => b.batch_file_name === "answers.csv")).toBe(true);
    expect(bodies[0].batch_id).toBe(run.id);

    // Nothing from this run is written locally. (What is in there is the demo
    // history that resolving an actor still seeds - see the note below.)
    const stored = JSON.parse(
      localStorage.getItem("pp.history.v2") ?? "[]",
    ) as { id?: string }[];
    expect(stored.some((e) => e.id === run.id)).toBe(false);
  });

  it("puts flagged rows first", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        const body = JSON.parse(init?.body as string) as {
          external_ref: string;
        };
        const human = body.external_ref === "A";
        return Promise.resolve({
          ok: true,
          status: 201,
          json: () =>
            Promise.resolve({
              ...CHECK,
              check_id: `check-${body.external_ref}`,
              external_ref: body.external_ref,
              verdict: human ? "human_written" : "ai_generated",
              raw_score: human ? 0.1 : 0.9,
            }),
        });
      }),
    );

    const run = await runBatch(INSTRUCTOR, "answers.csv", [
      input("A"),
      input("B"),
    ]);

    expect(run.rows[0].verdict).toBe("ai_generated");
  });
});
