import type {
  AbstainReason,
  BatchFailure,
  BatchRow,
  BatchRowInput,
  BatchRun,
  CheckInput,
  CueCode,
  DetectorCapabilities,
  HistoryEntry,
  SingleCheck,
  Strictness,
  Verdict,
} from "../types";
import {
  ABSTAIN_TEXT,
  CUE_TEXT,
  STRICTNESS_TEXT,
  VERDICT_TEXT,
} from "../types";
import * as stub from "./stub";
import type { User } from "./auth";
import { ApiError, apiRequest } from "./client";
import { describeCheckFailure } from "../lib/checkFailure";

export const checkKeys = {
  all: ["checks"] as const,
  history: () => [...checkKeys.all, "history"] as const,
  entry: (id: string) => [...checkKeys.all, "entry", id] as const,
  capabilities: () => [...checkKeys.all, "capabilities"] as const,
};

const DETECTOR_PATH = "/api/detector";

interface StrictnessLevelResponse {
  level: string;
  target_fpr: number | null;
}

interface DetectorResponse {
  model_version: string;
  requires_question_text: boolean;
  min_answer_chars: number;
  max_answer_chars: number;
  strictness_levels: StrictnessLevelResponse[];
  supports_explanation: boolean;
  supports_spans: boolean;
}

function toStrictnessLevels(rows: StrictnessLevelResponse[]): Strictness[] {
  return rows
    .map((row) => row.level)
    .filter((level): level is Strictness => level in STRICTNESS_TEXT);
}

function toDetectorCapabilities(row: DetectorResponse): DetectorCapabilities {
  return {
    modelVersion: row.model_version,
    requiresQuestionText: row.requires_question_text,
    minAnswerChars: row.min_answer_chars,
    maxAnswerChars: row.max_answer_chars,
    strictnessLevels: toStrictnessLevels(row.strictness_levels ?? []),
    supportsExplanation: row.supports_explanation,
    supportsSpans: row.supports_spans,
  };
}

export async function getCapabilities(
  signal?: AbortSignal,
): Promise<DetectorCapabilities> {
  return toDetectorCapabilities(
    await apiRequest<DetectorResponse>(DETECTOR_PATH, { signal }),
  );
}

export function listHistory(
  actor: User,
  signal?: AbortSignal,
): Promise<HistoryEntry[]> {
  return stub.listHistory(actor, signal);
}

export function getEntry(
  actor: User,
  id: string,
  signal?: AbortSignal,
): Promise<HistoryEntry | undefined> {
  return stub.getEntry(actor, id, signal);
}

const CHECKS_PATH = "/api/checks";

interface CheckDetectorResponse {
  model_version: string;
  calibration_version: string | null;
  strictness_applied: string;
  threshold_applied: number | null;
  target_fpr: number | null;
  used_question_text: boolean;
}

interface CheckResponse {
  check_id: string;
  actor_id: string;
  batch_id: string | null;
  external_ref: string | null;
  verdict: string;
  raw_score: number;
  confidence: number | null;
  abstain_reason: string | null;
  truncated: boolean | null;
  detector: CheckDetectorResponse;
  answer_text: string | null;
  question_text: string | null;
  explanation: { cues?: string[] } | null;
  created_at: string;
  latency_ms: number | null;
}

const known = <K extends string>(
  copy: Record<K, string>,
  value: string | null | undefined,
): K | null => (value != null && value in copy ? (value as K) : null);

function toCues(cues: string[] | undefined): CueCode[] {
  return (cues ?? []).filter((cue): cue is CueCode => cue in CUE_TEXT);
}

function toSingleCheck(row: CheckResponse, asked: Strictness): SingleCheck {
  const cues = toCues(row.explanation?.cues);
  return {
    kind: "single",
    checkId: row.check_id,
    actorId: row.actor_id,
    batchId: row.batch_id,
    externalRef: row.external_ref,
    verdict: known<Verdict>(VERDICT_TEXT, row.verdict) ?? "uncertain",
    rawScore: row.raw_score,
    confidence: row.confidence,
    abstainReason: known<NonNullable<AbstainReason>>(
      ABSTAIN_TEXT,
      row.abstain_reason,
    ),
    truncated: row.truncated,
    detector: {
      modelVersion: row.detector.model_version,
      calibrationVersion: row.detector.calibration_version,
      strictnessApplied:
        known<Strictness>(STRICTNESS_TEXT, row.detector.strictness_applied) ??
        asked,
      thresholdApplied: row.detector.threshold_applied,
      targetFpr: row.detector.target_fpr,
      usedQuestionText: row.detector.used_question_text,
    },
    answerText: row.answer_text,
    questionText: row.question_text,
    explanation: cues.length > 0 ? { cues } : null,
    createdAt: row.created_at,
    latencyMs: row.latency_ms,
  };
}

async function postCheck(input: CheckInput): Promise<SingleCheck> {
  stub.validateCheckInput(input);
  const strictness = input.strictness ?? "standard";

  return toSingleCheck(
    await apiRequest<CheckResponse>(CHECKS_PATH, {
      method: "POST",
      body: {
        answer_text: input.answerText.trim(),
        question_text: input.questionText?.trim() || null,
        external_ref: input.externalRef?.trim() || null,
        strictness,
        retain_answer: input.retainAnswer ?? true,
      },
    }),
    strictness,
  );
}

export async function checkAnswer(
  actor: User,
  input: CheckInput,
): Promise<SingleCheck> {
  stub.requireScreeningAccess(actor);
  const entry = await postCheck(input);
  stub.rememberCheck(entry);
  return entry;
}

const BATCH_CONCURRENCY = 4;

async function mapWithLimit<T, R>(
  items: T[],
  limit: number,
  work: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const out = new Array<R>(items.length);
  let next = 0;

  const worker = async () => {
    for (;;) {
      const index = next++;
      if (index >= items.length) return;
      out[index] = await work(items[index], index);
    }
  };

  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, worker),
  );
  return out;
}

type RowOutcome =
  | { ok: true; row: BatchRow }
  | { ok: false; failure: BatchFailure };

export async function runBatch(
  actor: User,
  fileName: string,
  inputs: BatchRowInput[],
  strictness: Strictness = "standard",
  onProgress?: (done: number, total: number) => void,
): Promise<BatchRun> {
  stub.requireScreeningAccess(actor);

  const batchId = crypto.randomUUID();
  let done = 0;

  const outcomes = await mapWithLimit(
    inputs,
    BATCH_CONCURRENCY,
    async (input): Promise<RowOutcome> => {
      try {
        const entry = await postCheck({
          answerText: input.answerText,
          questionText: input.questionText,
          externalRef: input.externalRef,
          strictness,
        });
        return { ok: true, row: { ...entry, batchId } };
      } catch (error) {
        return {
          ok: false,
          failure: {
            externalRef: input.externalRef,
            reason: describeCheckFailure(error),
          },
        };
      } finally {
        onProgress?.(++done, inputs.length);
      }
    },
  );

  const rows: BatchRow[] = [];
  const failures: BatchFailure[] = [];
  for (const outcome of outcomes) {
    if (outcome.ok) rows.push(outcome.row);
    else failures.push(outcome.failure);
  }

  if (rows.length === 0 && failures.length > 0) {
    throw new ApiError(
      502,
      failures.length === 1
        ? failures[0].reason
        : `None of the ${failures.length} rows could be checked. ${failures[0].reason}`,
    );
  }

  const counts: Record<Verdict, number> = {
    ai_generated: 0,
    uncertain: 0,
    human_written: 0,
  };
  for (const row of rows) counts[row.verdict]++;

  const order: Record<Verdict, number> = {
    ai_generated: 0,
    uncertain: 1,
    human_written: 2,
  };
  rows.sort(
    (a, b) => order[a.verdict] - order[b.verdict] || b.rawScore - a.rawScore,
  );

  const run: BatchRun = {
    id: batchId,
    kind: "batch",
    fileName,
    createdAt: new Date().toISOString(),
    strictness,
    rows,
    counts,
    ...(failures.length > 0 ? { failures } : {}),
  };

  stub.rememberCheck(run);
  return run;
}

export function hasScreeningAccess(actor: User): boolean {
  return stub.hasScreeningAccess(actor);
}
