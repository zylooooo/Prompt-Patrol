import type {
  BatchRowInput,
  BatchRun,
  CheckInput,
  HistoryEntry,
  SingleCheck,
  Strictness,
} from "./types";
import * as stub from "./stub";

export const checkKeys = {
  all: ["checks"] as const,
  history: () => [...checkKeys.all, "history"] as const,
  entry: (id: string) => [...checkKeys.all, "entry", id] as const,
};

export function listHistory(
  actorEmail: string,
  signal?: AbortSignal,
): Promise<HistoryEntry[]> {
  return stub.listHistory(actorEmail, signal);
}

export function getEntry(
  actorEmail: string,
  id: string,
  signal?: AbortSignal,
): Promise<HistoryEntry | undefined> {
  return stub.getEntry(actorEmail, id, signal);
}

export function checkAnswer(
  actorEmail: string,
  input: CheckInput,
): Promise<SingleCheck> {
  return stub.checkAnswer(actorEmail, input);
}

export function runBatch(
  actorEmail: string,
  fileName: string,
  rows: BatchRowInput[],
  strictness?: Strictness,
  onProgress?: (done: number, total: number) => void,
): Promise<BatchRun> {
  return stub.runBatch(actorEmail, fileName, rows, strictness, onProgress);
}

export function hasScreeningAccess(actorEmail: string): boolean {
  return stub.hasScreeningAccess(actorEmail);
}

export const MODEL_VERSION = stub.MODEL_VERSION;
