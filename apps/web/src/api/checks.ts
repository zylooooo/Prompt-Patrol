import type {
  BatchRowInput,
  BatchRun,
  CheckInput,
  DetectorCapabilities,
  HistoryEntry,
  SingleCheck,
  Strictness,
} from "../types";
import * as stub from "./stub";
import type { User } from "./auth";
import { apiRequest } from "./client";
import { STRICTNESS_TEXT } from "../types";

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

export function checkAnswer(
  actor: User,
  input: CheckInput,
): Promise<SingleCheck> {
  return stub.checkAnswer(actor, input);
}

export function runBatch(
  actor: User,
  fileName: string,
  rows: BatchRowInput[],
  strictness?: Strictness,
  onProgress?: (done: number, total: number) => void,
): Promise<BatchRun> {
  return stub.runBatch(actor, fileName, rows, strictness, onProgress);
}

export function hasScreeningAccess(actor: User): boolean {
  return stub.hasScreeningAccess(actor);
}
