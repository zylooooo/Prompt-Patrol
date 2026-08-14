import type {
  BatchRowInput,
  BatchRun,
  CheckInput,
  HistoryEntry,
  SingleCheck,
  Strictness,
} from "./types";
import * as stub from "./stub";
import type { User } from "./auth";

export const checkKeys = {
  all: ["checks"] as const,
  history: () => [...checkKeys.all, "history"] as const,
  entry: (id: string) => [...checkKeys.all, "entry", id] as const,
};

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

export const MODEL_VERSION = stub.MODEL_VERSION;
