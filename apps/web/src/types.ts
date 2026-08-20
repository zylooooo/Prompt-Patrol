export type Verdict = "ai_generated" | "human_written" | "uncertain";

export const VERDICT_TEXT: Record<Verdict, string> = {
  ai_generated: "Likely AI-generated",
  uncertain: "Uncertain",
  human_written: "Likely human",
};

export type Strictness = "lenient" | "standard" | "strict";

export const STRICTNESS_TEXT: Record<Strictness, string> = {
  lenient: "Lenient",
  standard: "Standard",
  strict: "Strict",
};

export const STRICTNESS_HINT: Record<Strictness, string> = {
  lenient: "Flags more answers, about 5 in 100 flagged in error",
  standard: "Flags about 1 in 100 in error",
  strict: "Flags only high-confidence cases, about 1 in 1000 in error",
};

export type AbstainReason =
  | "answer_too_short"
  | "low_signal"
  | "score_in_abstention_band"
  | null;

export const ABSTAIN_TEXT: Record<NonNullable<AbstainReason>, string> = {
  answer_too_short: "The answer is too short to judge.",
  low_signal: "The writing carries too little signal either way.",
  score_in_abstention_band:
    "The score sits too close to the flag threshold to call.",
};

export type CueCode =
  | "formal_vocabulary"
  | "uniform_sentence_length"
  | "long_sentences"
  | "informal_phrasing"
  | "short_answer";

export const CUE_TEXT: Record<CueCode, string> = {
  formal_vocabulary: "Vocabulary is more formal than typical short answers.",
  uniform_sentence_length: "Sentence lengths are unusually uniform.",
  long_sentences: "Sentences are long and densely constructed.",
  informal_phrasing:
    "Informal phrasing lowers the likelihood of AI generation.",
  short_answer: "Answer is short, so the signal is weak.",
};

export interface Explanation {
  cues: CueCode[];
}

export interface DetectorInfo {
  modelVersion: string;
  calibrationVersion: string | null;
  strictnessApplied: Strictness;
  thresholdApplied: number | null;
  targetFpr: number | null;
  usedQuestionText: boolean;
}

export const ANSWER_MIN_CHARS = 10;
export const ANSWER_MAX_CHARS = 10000;
export const QUESTION_MAX_CHARS = 2000;
export const EXTERNAL_REF_MAX_CHARS = 128;

export interface CheckResult {
  checkId: string;
  actorId: string;
  batchId: string | null;
  externalRef: string | null;
  verdict: Verdict;
  rawScore: number;
  confidence: number | null;
  abstainReason: AbstainReason;
  truncated: boolean | null;
  detector: DetectorInfo;
  answerText: string | null;
  questionText: string | null;
  explanation: Explanation | null;
  createdAt: string;
  latencyMs: number | null;
}

export type DetectorStatus = "ready" | "loading" | "unavailable";

export interface DetectorCapabilities {
  modelVersion: string;
  requiresQuestionText: boolean;
  minAnswerChars: number;
  maxAnswerChars: number;
  strictnessLevels: Strictness[];
  supportsExplanation: boolean;
  supportsSpans: boolean;
}

export interface BatchRowInput {
  externalRef: string;
  answerText: string;
  questionText?: string;
}

export type BatchRow = CheckResult;

export interface BatchFailure {
  externalRef: string;
  reason: string;
}

export interface BatchRun {
  id: string;
  kind: "batch";
  fileName: string;
  createdAt: string;
  strictness: Strictness;
  rows: BatchRow[];
  counts: Record<Verdict, number>;
  failures?: BatchFailure[];
}

export interface SingleCheck extends CheckResult {
  kind: "single";
}

export type HistoryEntry = SingleCheck | BatchRun;

export function entryId(entry: HistoryEntry): string {
  return entry.kind === "batch" ? entry.id : entry.checkId;
}

export type UserRole = "root_admin" | "instructor" | "teaching_assistant";

export const ROLE_TEXT: Record<UserRole, string> = {
  root_admin: "Admin",
  instructor: "Instructor",
  teaching_assistant: "Teaching Assistant",
};

const ROLE_ORDER: Record<UserRole, number> = {
  teaching_assistant: 0,
  instructor: 1,
  root_admin: 2,
};

export function atLeastRole(role: UserRole, min: UserRole): boolean {
  return ROLE_ORDER[role] >= ROLE_ORDER[min];
}

export function canAccess(
  role: UserRole,
  allowed?: readonly UserRole[],
): boolean {
  return allowed === undefined || allowed.includes(role);
}

export type UserStatus = "active" | "deactivated" | "deleted";

export const USER_STATUS_TEXT: Record<UserStatus, string> = {
  active: "Active",
  deactivated: "Deactivated",
  deleted: "Deleted",
};

export interface AppUser {
  id: string;
  email: string;
  name: string | null;
  role: UserRole;
  status: UserStatus;
  provisionedBy: string | null;
  createdAt: string;
}

export function isActive(user: AppUser): boolean {
  return user.status === "active";
}

export function canReactivate(user: AppUser): boolean {
  return user.status === "deactivated";
}

export function statusLabel(user: AppUser): string {
  return USER_STATUS_TEXT[user.status];
}

export function displayName(user: AppUser): string {
  return user.name ?? user.email.split("@")[0];
}

export function roleLabel(user: AppUser): string {
  return ROLE_TEXT[user.role];
}

export interface CheckInput {
  answerText: string;
  questionText?: string;
  externalRef?: string;
  strictness?: Strictness;
  retainAnswer?: boolean;
}

export interface CreateAccountInput {
  email: string;
  role: UserRole;
  name?: string;
  supervisorId?: string | null;
}

export type DeactivationPlan =
  | { mode: "reassign"; toId: string }
  | { mode: "deactivate" }
  | { mode: "leave" };

export interface DeactivationOutcome {
  reassigned: number;
  deactivated: number;
  leftUnassigned: number;
}
