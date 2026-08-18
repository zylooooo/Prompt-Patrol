// ---------------------------------------------------------------------------
// STUB BACKEND — NOT A SECURITY BOUNDARY.
//
// Stands in for the checks and users modules, which do not exist server-side
// yet. Delete this entire file once POST /api/checks and /api/users ship, and
// replace the bodies in ./checks and ./users with apiRequest calls.
//
// Every permission check below is COSMETIC. It shapes the UI so the demo makes
// sense; it stops nobody. The data lives in this browser's localStorage, so any
// caller can edit it from devtools. Today the only role the server enforces is
// in auth.py's `me` route; nothing here is checked again by anyone. The server
// must enforce all of these rules independently and must never assume the
// client did.
//
// Seed accounts use example.com deliberately: fabricated people must not sit on
// a real institutional domain. They are not creatable through the UI, which
// enforces the SMU rule — mirroring reality, where seeded accounts come from
// scripts/provision_user rather than the roster screen.
// ---------------------------------------------------------------------------

import {
  ANSWER_MAX_CHARS,
  ANSWER_MIN_CHARS,
  atLeastRole,
  EXTERNAL_REF_MAX_CHARS,
  QUESTION_MAX_CHARS,
  type AbstainReason,
  type AppUser,
  type BatchRow,
  type BatchRowInput,
  type BatchRun,
  type CueCode,
  type DetectorInfo,
  type Explanation,
  type HistoryEntry,
  type SingleCheck,
  type Strictness,
  type UserRole,
  type Verdict,
  type CheckInput,
  type CreateAccountInput,
} from "../types";
import type { User } from "./auth";
import { ApiError } from "./client";

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason as Error);
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(signal.reason as Error);
      },
      { once: true },
    );
  });
}

const newId = () => crypto.randomUUID();

const sameEmail = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

export const MODEL_VERSION = "roberta-base-detector-v0";

const THRESHOLDS: Record<Strictness, number> = {
  lenient: 0.4,
  standard: 0.5,
  strict: 0.65,
};

const TARGET_FPR: Record<Strictness, number> = {
  lenient: 0.05,
  standard: 0.01,
  strict: 0.001,
};

const ABSTENTION_BAND = 0.08;
const MIN_SIGNAL_WORDS = 10;

const FORMAL_MARKERS = [
  "furthermore",
  "moreover",
  "typically",
  "utilize",
  "thereby",
  "consequently",
  "in addition",
  "specifically",
  "is defined as",
  "refers to",
  "ensures",
  "facilitates",
];

const INFORMAL_PATTERN = /\b(idk|lol|dunno|stuff|kinda|gonna|btw|imo)\b/i;

function hashToUnit(text: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0) / 0xffffffff;
}

interface Analysis {
  rawScore: number;
  verdict: Verdict;
  abstainReason: AbstainReason;
  explanation: Explanation | null;
  detector: DetectorInfo;
}

function decide(
  score: number,
  threshold: number,
  tooShort: boolean,
): { verdict: Verdict; abstainReason: AbstainReason } {
  if (tooShort) {
    return { verdict: "uncertain", abstainReason: "answer_too_short" };
  }
  if (Math.abs(score - threshold) <= ABSTENTION_BAND) {
    return { verdict: "uncertain", abstainReason: "score_in_abstention_band" };
  }
  return {
    verdict: score > threshold ? "ai_generated" : "human_written",
    abstainReason: null,
  };
}

function analyseAnswer(
  answerText: string,
  strictness: Strictness = "standard",
  usedQuestionText = false,
): Analysis {
  const text = answerText.trim();
  const words = text.split(/\s+/).filter(Boolean);
  const sentences = text
    .split(/[.!?]+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);

  let score = 0.25 + 0.5 * hashToUnit(text.toLowerCase());
  const cues: CueCode[] = [];

  const lower = text.toLowerCase();
  const formalHits = FORMAL_MARKERS.filter((marker) =>
    lower.includes(marker),
  ).length;
  if (formalHits > 0) {
    score += Math.min(formalHits * 0.05, 0.16);
    cues.push("formal_vocabulary");
  }

  if (sentences.length >= 2) {
    const lengths = sentences.map((sentence) => sentence.split(/\s+/).length);
    const spread = Math.max(...lengths) - Math.min(...lengths);
    if (spread <= 4) {
      score += 0.08;
      cues.push("uniform_sentence_length");
    }
  }

  const avgSentenceLen = words.length / Math.max(sentences.length, 1);
  if (avgSentenceLen >= 18) {
    score += 0.08;
    cues.push("long_sentences");
  }

  if (INFORMAL_PATTERN.test(text)) {
    score -= 0.28;
    cues.push("informal_phrasing");
  }

  const tooShort = words.length < MIN_SIGNAL_WORDS;
  if (tooShort) {
    score = 0.5 + (score - 0.5) * 0.45;
    cues.push("short_answer");
  }

  score = Math.min(0.97, Math.max(0.03, score));
  score = Math.round(score * 100) / 100;

  const threshold = THRESHOLDS[strictness];

  return {
    rawScore: score,
    ...decide(score, threshold, tooShort),
    explanation: cues.length > 0 ? { cues } : null,
    detector: {
      modelVersion: MODEL_VERSION,
      calibrationVersion: null,
      strictnessApplied: strictness,
      thresholdApplied: threshold,
      targetFpr: TARGET_FPR[strictness],
      usedQuestionText,
    },
  };
}

const HISTORY_KEY = "pp.history.v2";
// v3 drops rows persisted with the old `deletedAt` field, which read back with
// no `status` and rendered a blank chip.
const USERS_KEY = "pp.users.v3";
const LEGACY_USERS_KEYS = ["pp.users.v2"];
// Held "who supervises whom" until the server took it over. Kept only so the
// stale blob gets cleared out of browsers that still have one.
const LEGACY_SUPERVISION_KEY = "pp.supervision.v2";
const HISTORY_CAP = 200;

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown) {
  localStorage.setItem(key, JSON.stringify(value));
}

function loadHistory(): HistoryEntry[] {
  return readJson<HistoryEntry[]>(HISTORY_KEY, []);
}

// Internal again: checks are persisted server-side since 2026-08-18, so
// `api/checks.ts` no longer mirrors anything here. Only the stub's own
// (now unused by the app) check functions still write history.
function rememberCheck(entry: HistoryEntry) {
  let list = [entry, ...loadHistory()].slice(0, HISTORY_CAP);
  for (;;) {
    try {
      writeJson(HISTORY_KEY, list);
      return;
    } catch {
      if (list.length > 1) {
        list = list.slice(0, Math.ceil(list.length / 2));
      } else {
        throw new ApiError(
          507,
          "History storage is full. Clear old browser site data to free space.",
        );
      }
    }
  }
}

const HISTORY_SEEDED_KEY = "pp.history.seeded.v2";

const SEED_ANSWERS: {
  ref: string;
  question: string;
  answer: string;
  at: string;
}[] = [
  {
    ref: "ECON101-Q3-0184",
    question: "Explain how equilibrium price responds to a rise in demand.",
    answer:
      "Supply and demand determine the equilibrium price in a competitive market. Furthermore, when demand rises and supply is held constant, the equilibrium price typically increases. This relationship is defined as the law of demand, and it specifically ensures that markets clear over time.",
    at: "2026-07-11T02:18:00.000Z",
  },
  {
    ref: "CS201-Q1-0092",
    question: "Why does this loop read past the end of the array?",
    answer:
      "my answer is that the loop runs one extra time because the condition uses less than or equal instead of less than, so it goes off the end of the array",
    at: "2026-07-11T02:05:00.000Z",
  },
  {
    ref: "ECON101-Q4-0211",
    question: "What happened to ticket prices in the case study?",
    answer:
      "honestly i think the answer is that prices go up when more people want the thing. idk how to explain it better but thats what happened in the example we did in class lol",
    at: "2026-07-10T09:31:00.000Z",
  },
  {
    ref: "ECON101-Q2-0177",
    question: "What happens to price when demand rises?",
    answer: "It increases.",
    at: "2026-07-10T09:12:00.000Z",
  },
];

const SEED_BATCH_ROWS: { ref: string; answer: string }[] = [
  {
    ref: "BIO210-0001",
    answer:
      "The mitochondria produces ATP through oxidative phosphorylation, which occurs across the inner membrane where the electron transport chain establishes a proton gradient that ATP synthase subsequently uses to phosphorylate ADP into ATP for cellular work.",
  },
  {
    ref: "BIO210-0002",
    answer:
      "Normalisation reduces redundancy by splitting tables so each fact is stored once. Third normal form removes transitive dependencies between non-key attributes.",
  },
  {
    ref: "BIO210-0003",
    answer:
      "basically the cell wall keeps the shape and stops it bursting when water comes in, thats the main thing i remember from the practical we did",
  },
  {
    ref: "BIO210-0004",
    answer:
      "my answer is that the loop runs one extra time because the condition uses less than or equal instead of less than, so it goes off the end of the array",
  },
  { ref: "BIO210-0005", answer: "It increases." },
];

const SEED_BATCH_AT = "2026-07-11T06:40:00.000Z";

function seedHistoryFor(owner: AppUser) {
  const seeded = readJson<string[]>(HISTORY_SEEDED_KEY, []);
  if (seeded.includes(owner.id)) return;

  const singles: SingleCheck[] = SEED_ANSWERS.map((seed) => {
    const analysis = analyseAnswer(seed.answer, "standard", true);
    return {
      kind: "single",
      checkId: newId(),
      actorId: owner.id,
      batchId: null,
      externalRef: seed.ref,
      verdict: analysis.verdict,
      rawScore: analysis.rawScore,
      confidence: null,
      abstainReason: analysis.abstainReason,
      truncated: false,
      detector: analysis.detector,
      answerText: seed.answer,
      questionText: seed.question,
      explanation: analysis.explanation,
      createdAt: seed.at,
      latencyMs: 610,
    };
  });

  const batchId = newId();
  const rows: BatchRow[] = SEED_BATCH_ROWS.map((seed) => {
    const analysis = analyseAnswer(seed.answer, "standard", false);
    return {
      checkId: newId(),
      actorId: owner.id,
      batchId,
      externalRef: seed.ref,
      verdict: analysis.verdict,
      rawScore: analysis.rawScore,
      confidence: null,
      abstainReason: analysis.abstainReason,
      truncated: false,
      detector: analysis.detector,
      answerText: seed.answer,
      questionText: null,
      explanation: analysis.explanation,
      createdAt: SEED_BATCH_AT,
      latencyMs: null,
    };
  });

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

  const batch: BatchRun = {
    id: batchId,
    kind: "batch",
    fileName: "bio210-midterm-sample.csv",
    createdAt: SEED_BATCH_AT,
    strictness: "standard",
    rows,
    counts,
  };

  const entries: HistoryEntry[] = [batch, ...singles];
  writeJson(HISTORY_KEY, [...entries, ...loadHistory()].slice(0, HISTORY_CAP));
  writeJson(HISTORY_SEEDED_KEY, [...seeded, owner.id]);
}

const T0 = "2026-07-01T00:00:00.000Z";
const T1 = "2026-07-08T04:00:00.000Z";
const T2 = "2026-07-09T02:00:00.000Z";

const ID_ADMIN = "00000000-0000-4000-8000-000000000001";
const ID_INSTRUCTOR_A = "00000000-0000-4000-8000-000000000002";
const ID_INSTRUCTOR_B = "00000000-0000-4000-8000-000000000003";
const ID_TA_A = "00000000-0000-4000-8000-000000000004";
const ID_TA_B = "00000000-0000-4000-8000-000000000005";
const ID_TA_C = "00000000-0000-4000-8000-000000000006";
const ID_TA_D = "00000000-0000-4000-8000-000000000007";

const SEED_USERS: AppUser[] = [
  {
    id: ID_ADMIN,
    email: "admin@example.com",
    name: "Demo Admin",
    role: "root_admin",
    provisionedBy: null,
    status: "active",
    createdAt: T0,
  },
  {
    id: ID_INSTRUCTOR_A,
    email: "instructor.a@example.com",
    name: "Demo Instructor A",
    role: "instructor",
    provisionedBy: ID_ADMIN,
    status: "active",
    createdAt: T0,
  },
  {
    id: ID_INSTRUCTOR_B,
    email: "instructor.b@example.com",
    name: "Demo Instructor B",
    role: "instructor",
    provisionedBy: ID_ADMIN,
    status: "active",
    createdAt: T1,
  },
  {
    id: ID_TA_A,
    email: "ta.a@example.com",
    name: "Demo TA A",
    role: "teaching_assistant",
    provisionedBy: ID_INSTRUCTOR_A,
    status: "active",
    createdAt: T1,
  },
  {
    id: ID_TA_B,
    email: "ta.b@example.com",
    name: "Demo TA B",
    role: "teaching_assistant",
    provisionedBy: ID_INSTRUCTOR_A,
    status: "active",
    createdAt: T1,
  },
  {
    id: ID_TA_C,
    email: "ta.c@example.com",
    name: "Demo TA C",
    role: "teaching_assistant",
    provisionedBy: ID_INSTRUCTOR_B,
    status: "active",
    createdAt: T2,
  },
  {
    id: ID_TA_D,
    email: "ta.d@example.com",
    name: "Demo TA D",
    role: "teaching_assistant",
    // Deliberately nobody: the demo needs one assistant who shows up under the
    // Unassigned filter and cannot screen.
    provisionedBy: null,
    status: "active",
    createdAt: T2,
  },
];

function assertSeedsConsistent() {
  const byId = new Map(SEED_USERS.map((user) => [user.id, user]));
  const problems: string[] = [];

  if (new Set(SEED_USERS.map((u) => u.id)).size !== SEED_USERS.length) {
    problems.push("duplicate user ids");
  }
  if (
    new Set(SEED_USERS.map((u) => u.email.toLowerCase())).size !==
    SEED_USERS.length
  ) {
    problems.push("duplicate user emails");
  }

  // provisionedBy is the supervision edge now, so the seeds have to satisfy the
  // same rule the server enforces: an assistant's supervisor is an instructor.
  for (const user of SEED_USERS) {
    if (user.provisionedBy === null) continue;
    const supervisor = byId.get(user.provisionedBy);
    if (!supervisor) {
      problems.push(`${user.email}: provisionedBy references an unknown user`);
      continue;
    }
    if (
      user.role === "teaching_assistant" &&
      supervisor.role !== "instructor"
    ) {
      problems.push(`${user.email}: supervised by a ${supervisor.role}`);
    }
    if (user.createdAt < supervisor.createdAt) {
      problems.push(`${user.email}: predates ${supervisor.email}`);
    }
  }

  if (problems.length > 0) {
    throw new Error(`Inconsistent stub seed data:\n- ${problems.join("\n- ")}`);
  }
}

if (import.meta.env.DEV) assertSeedsConsistent();

function loadUsers(): AppUser[] {
  if (localStorage.getItem(USERS_KEY) === null) {
    for (const key of LEGACY_USERS_KEYS) localStorage.removeItem(key);
    writeJson(USERS_KEY, SEED_USERS);
    return SEED_USERS;
  }
  return readJson<AppUser[]>(USERS_KEY, []);
}

function saveUsers(users: AppUser[]) {
  writeJson(USERS_KEY, users);
}

// Drops every key this module owns. Goes away with the rest of the file.
export function clearStoredData(): void {
  for (const key of [
    HISTORY_KEY,
    USERS_KEY,
    ...LEGACY_USERS_KEYS,
    LEGACY_SUPERVISION_KEY,
    HISTORY_SEEDED_KEY,
  ]) {
    localStorage.removeItem(key);
  }
}

// Terminal removal. Keeps the row for history but frees the email, mirroring the
// backend's partial unique index, so the same person can be provisioned again.
export function deleteUser(actor: User, id: string): Promise<AppUser> {
  const resolved = requireAdmin(actor);
  const users = loadUsers();
  const target = users.find((u) => u.id === id);
  if (!target) throw new ApiError(404, "User not found.");
  if (target.id === resolved.id) {
    throw new ApiError(403, "You cannot delete your own account.");
  }
  if (target.role === "root_admin") {
    throw new ApiError(403, "Admin accounts cannot be deleted.");
  }
  if (target.status === "deleted") {
    throw new ApiError(409, "This account is already deleted.");
  }
  target.status = "deleted";
  saveUsers(users);
  return Promise.resolve({ ...target });
}

export function findUserByEmail(email: string): AppUser | undefined {
  return loadUsers().find((user) => sameEmail(user.email, email));
}

export function findUserById(id: string): AppUser | undefined {
  return loadUsers().find((user) => user.id === id);
}

function requireActor(actor: User): AppUser {
  const existing = findUserByEmail(actor.email);
  if (existing) {
    seedHistoryFor(existing);
    if (existing.role !== actor.role) {
      const users = loadUsers().map((user) =>
        user.id === existing.id ? { ...user, role: actor.role } : user,
      );
      saveUsers(users);
      return { ...existing, role: actor.role };
    }
    return existing;
  }

  const adopted: AppUser = {
    id: newId(),
    email: actor.email,
    name: null,
    role: actor.role,
    provisionedBy: null,
    status: "active",
    createdAt: new Date().toISOString(),
  };
  saveUsers([...loadUsers(), adopted]);
  seedHistoryFor(adopted);
  return adopted;
}

function requireRole(actor: User, min: UserRole): AppUser {
  const resolved = requireActor(actor);
  if (!atLeastRole(resolved.role, min)) {
    throw new ApiError(403, "You do not have access to this.");
  }
  return resolved;
}

const requireAdmin = (actor: User) => requireRole(actor, "root_admin");

// Genuine client-side input validation, not a fake backend. Exported so the real
// `checkAnswer` keeps the friendlier wording and the question/reference limits
// the server does not have. Move into `./checks` when this file goes.
export function validateCheckInput(input: CheckInput) {
  const answer = input.answerText.trim();
  if (answer.length < ANSWER_MIN_CHARS) {
    throw new ApiError(400, `Enter at least ${ANSWER_MIN_CHARS} characters.`);
  }
  if (answer.length > ANSWER_MAX_CHARS) {
    throw new ApiError(
      400,
      `Answers are limited to ${ANSWER_MAX_CHARS.toLocaleString()} characters.`,
    );
  }
  if (input.questionText && input.questionText.length > QUESTION_MAX_CHARS) {
    throw new ApiError(
      400,
      `Questions are limited to ${QUESTION_MAX_CHARS.toLocaleString()} characters.`,
    );
  }
  if (input.externalRef && input.externalRef.length > EXTERNAL_REF_MAX_CHARS) {
    throw new ApiError(
      400,
      `Reference is limited to ${EXTERNAL_REF_MAX_CHARS} characters.`,
    );
  }
}

export async function checkAnswer(
  actor: User,
  input: CheckInput,
): Promise<SingleCheck> {
  const resolved = requireActor(actor);
  validateCheckInput(input);
  const startedAt = performance.now();
  await delay(650);

  const strictness = input.strictness ?? "standard";
  const questionText = input.questionText?.trim() || null;
  const analysis = analyseAnswer(
    input.answerText,
    strictness,
    questionText !== null,
  );
  const retain = input.retainAnswer ?? true;

  const entry: SingleCheck = {
    kind: "single",
    checkId: newId(),
    actorId: resolved.id,
    batchId: null,
    externalRef: input.externalRef?.trim() || null,
    verdict: analysis.verdict,
    rawScore: analysis.rawScore,
    confidence: null,
    abstainReason: analysis.abstainReason,
    truncated: false,
    detector: analysis.detector,
    answerText: retain ? input.answerText : null,
    questionText,
    explanation: analysis.explanation,
    createdAt: new Date().toISOString(),
    latencyMs: Math.round(performance.now() - startedAt),
  };
  rememberCheck(entry);
  return entry;
}

export async function runBatch(
  actor: User,
  fileName: string,
  inputs: BatchRowInput[],
  strictness: Strictness = "standard",
  onProgress?: (done: number, total: number) => void,
): Promise<BatchRun> {
  const resolved = requireActor(actor);
  const batchId = newId();
  const rows: BatchRow[] = [];

  for (let i = 0; i < inputs.length; i++) {
    await delay(24);
    const row = inputs[i];
    const questionText = row.questionText?.trim() || null;
    const analysis = analyseAnswer(
      row.answerText,
      strictness,
      questionText !== null,
    );
    rows.push({
      checkId: newId(),
      actorId: resolved.id,
      batchId,
      externalRef: row.externalRef,
      verdict: analysis.verdict,
      rawScore: analysis.rawScore,
      confidence: null,
      abstainReason: analysis.abstainReason,
      truncated: false,
      detector: analysis.detector,
      answerText: row.answerText,
      questionText,
      explanation: analysis.explanation,
      createdAt: new Date().toISOString(),
      latencyMs: null,
    });
    onProgress?.(i + 1, inputs.length);
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
  };
  rememberCheck(run);
  return run;
}

function ownedBy(entry: HistoryEntry, actorId: string): boolean {
  return entry.kind === "batch"
    ? entry.rows.every((row) => row.actorId === actorId)
    : entry.actorId === actorId;
}

export async function listHistory(
  actor: User,
  signal?: AbortSignal,
): Promise<HistoryEntry[]> {
  await delay(150, signal);
  const resolved = requireActor(actor);
  return loadHistory().filter((entry) => ownedBy(entry, resolved.id));
}

export async function getEntry(
  actor: User,
  id: string,
  signal?: AbortSignal,
): Promise<HistoryEntry | undefined> {
  await delay(120, signal);
  const resolved = requireActor(actor);
  return loadHistory()
    .filter((entry) => ownedBy(entry, resolved.id))
    .find(
      (entry) => (entry.kind === "batch" ? entry.id : entry.checkId) === id,
    );
}

export async function listUsers(
  actor: User,
  signal?: AbortSignal,
): Promise<AppUser[]> {
  await delay(150, signal);
  requireAdmin(actor);
  return loadUsers();
}

export async function createAccount(
  actor: User,
  input: CreateAccountInput,
): Promise<AppUser> {
  await delay(300);
  const resolved = requireActor(actor);
  const canCreate =
    input.role === "teaching_assistant"
      ? atLeastRole(resolved.role, "instructor")
      : atLeastRole(resolved.role, "root_admin");
  if (!canCreate) {
    throw new ApiError(403, "You cannot create an account with that role.");
  }
  if (input.role === "root_admin") {
    throw new ApiError(400, "Admin accounts are seeded, not created here.");
  }

  const email = input.email.trim();
  // if (!isSmuEmail(email)) {
  //   throw new ApiError(400, "Use an SMU email address.");
  // }
  if (findUserByEmail(email)) {
    throw new ApiError(409, "An account already exists for this email.");
  }

  const user: AppUser = {
    id: newId(),
    email,
    name: input.name?.trim() || null,
    role: input.role,
    provisionedBy: resolved.id,
    status: "active",
    createdAt: new Date().toISOString(),
  };
  saveUsers([...loadUsers(), user]);
  return user;
}

export async function setUserActive(
  actor: User,
  id: string,
  active: boolean,
): Promise<AppUser> {
  await delay(200);
  const resolved = requireAdmin(actor);
  if (resolved.id === id) {
    throw new ApiError(403, "You cannot deactivate your own account.");
  }
  const users = loadUsers();
  const user = users.find((candidate) => candidate.id === id);
  if (!user) throw new ApiError(404, "That account no longer exists.");
  // Mirrors the backend: deleted is terminal, so neither direction may touch it.
  // The UI hides these actions too, but the rule has to live here as well or the
  // two layers disagree about what is possible.
  if (user.status === "deleted") {
    throw new ApiError(
      409,
      "This account has been deleted and cannot be changed.",
    );
  }
  if (active && user.status === "active") {
    throw new ApiError(409, "This account is already active.");
  }
  if (!active && user.status === "deactivated") {
    throw new ApiError(409, "This account is already deactivated.");
  }

  user.status = active ? "active" : "deactivated";
  saveUsers(users);
  return user;
}

export async function resendInvite(actor: User, id: string): Promise<void> {
  await delay(200);
  const user = findUserById(id);
  if (!user) throw new ApiError(404, "That account no longer exists.");
  if (user.role === "teaching_assistant") {
    requireRole(actor, "instructor");
  } else {
    requireAdmin(actor);
  }
}
