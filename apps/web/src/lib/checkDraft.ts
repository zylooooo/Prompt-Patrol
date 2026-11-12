import type { Strictness } from "../types";

export interface CheckDraft {
  answer: string;
  question: string;
  strictness: Strictness;
}

// In memory only, never web storage: these are student answers (PDPA), and a
// shared lab machine must not keep them after the tab closes or the user signs
// out. Survives in-app navigation; a reload or sign-out (a full page load)
// drops it.
let draft: (CheckDraft & { userId: string }) | null = null;

export function readCheckDraft(userId: string): CheckDraft | null {
  return draft?.userId === userId ? draft : null;
}

export function writeCheckDraft(userId: string, next: CheckDraft): void {
  draft = { ...next, userId };
}

export function clearCheckDraft(): void {
  draft = null;
}

// The picked-but-not-started CSV. Same rules as the answer draft: memory only
// (a File can't go into web storage anyway), owner-scoped, gone on sign-out.
export interface BatchDraft {
  rawText: string;
  file: File;
  fileName: string;
  headers: string[];
  needsMapping: boolean;
  mapping: Record<string, string>;
  errors: string[];
  parsedCount: number | null;
  strictness: Strictness;
}

let batchDraft: (BatchDraft & { userId: string }) | null = null;

export function readBatchDraft(userId: string): BatchDraft | null {
  return batchDraft?.userId === userId ? batchDraft : null;
}

export function writeBatchDraft(userId: string, next: BatchDraft): void {
  batchDraft = { ...next, userId };
}

export function clearBatchDraft(): void {
  batchDraft = null;
}
