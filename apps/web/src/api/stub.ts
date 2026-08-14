import {
  ANSWER_MAX_CHARS,
  ANSWER_MIN_CHARS,
  atLeastRole,
  EXTERNAL_REF_MAX_CHARS,
  isActive,
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
  type SupervisionLink,
  type UserRole,
  type Verdict,
  type CheckInput,
  type CreateAccountInput,
  type DeactivationOutcome,
  type DeactivationPlan,
  type LookupResult,
} from "./types";
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
const USERS_KEY = "pp.users.v2";
const SUPERVISION_KEY = "pp.supervision.v2";
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

function prependHistory(entry: HistoryEntry) {
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
    deletedAt: null,
    createdAt: T0,
  },
  {
    id: ID_INSTRUCTOR_A,
    email: "instructor.a@example.com",
    name: "Demo Instructor A",
    role: "instructor",
    provisionedBy: ID_ADMIN,
    deletedAt: null,
    createdAt: T0,
  },
  {
    id: ID_INSTRUCTOR_B,
    email: "instructor.b@example.com",
    name: "Demo Instructor B",
    role: "instructor",
    provisionedBy: ID_ADMIN,
    deletedAt: null,
    createdAt: T1,
  },
  {
    id: ID_TA_A,
    email: "ta.a@example.com",
    name: "Demo TA A",
    role: "teaching_assistant",
    provisionedBy: ID_INSTRUCTOR_A,
    deletedAt: null,
    createdAt: T1,
  },
  {
    id: ID_TA_B,
    email: "ta.b@example.com",
    name: "Demo TA B",
    role: "teaching_assistant",
    provisionedBy: ID_INSTRUCTOR_A,
    deletedAt: null,
    createdAt: T1,
  },
  {
    id: ID_TA_C,
    email: "ta.c@example.com",
    name: "Demo TA C",
    role: "teaching_assistant",
    provisionedBy: ID_INSTRUCTOR_B,
    deletedAt: null,
    createdAt: T2,
  },
  {
    id: ID_TA_D,
    email: "ta.d@example.com",
    name: "Demo TA D",
    role: "teaching_assistant",
    provisionedBy: ID_INSTRUCTOR_B,
    deletedAt: null,
    createdAt: T2,
  },
];

const SEED_SUPERVISION: SupervisionLink[] = [
  { instructorId: ID_INSTRUCTOR_A, taId: ID_TA_A, createdAt: T1 },
  { instructorId: ID_INSTRUCTOR_A, taId: ID_TA_B, createdAt: T1 },
  { instructorId: ID_INSTRUCTOR_B, taId: ID_TA_B, createdAt: T1 },
  { instructorId: ID_INSTRUCTOR_B, taId: ID_TA_C, createdAt: T2 },
];

function loadUsers(): AppUser[] {
  if (localStorage.getItem(USERS_KEY) === null) {
    writeJson(USERS_KEY, SEED_USERS);
    return SEED_USERS;
  }
  return readJson<AppUser[]>(USERS_KEY, []);
}

function saveUsers(users: AppUser[]) {
  writeJson(USERS_KEY, users);
}

function loadSupervision(): SupervisionLink[] {
  if (localStorage.getItem(SUPERVISION_KEY) === null) {
    writeJson(SUPERVISION_KEY, SEED_SUPERVISION);
    return SEED_SUPERVISION;
  }
  return readJson<SupervisionLink[]>(SUPERVISION_KEY, []);
}

function saveSupervision(links: SupervisionLink[]) {
  writeJson(SUPERVISION_KEY, links);
}

export function findUserByEmail(email: string): AppUser | undefined {
  return loadUsers().find((user) => sameEmail(user.email, email));
}

export function findUserById(id: string): AppUser | undefined {
  return loadUsers().find((user) => user.id === id);
}

function requireActor(actorEmail: string): AppUser {
  const actor = findUserByEmail(actorEmail);
  if (!actor) throw new ApiError(401, "You are not signed in.");
  return actor;
}

function requireRole(actorEmail: string, min: UserRole): AppUser {
  const actor = requireActor(actorEmail);
  if (!atLeastRole(actor.role, min)) {
    throw new ApiError(403, "You do not have access to this.");
  }
  return actor;
}

const requireAdmin = (actorEmail: string) =>
  requireRole(actorEmail, "root_admin");

function requireScreeningAccess(actorEmail: string): AppUser {
  const actor = requireActor(actorEmail);
  if (actor.role !== "teaching_assistant") return actor;
  const linked = loadSupervision().some((link) => link.taId === actor.id);
  if (!linked) {
    throw new ApiError(
      403,
      "You are not assigned to an instructor yet, so there is nothing to screen.",
    );
  }
  return actor;
}

export function hasScreeningAccess(actorEmail: string): boolean {
  try {
    requireScreeningAccess(actorEmail);
    return true;
  } catch {
    return false;
  }
}

function requireAdminOrSupervisor(actorEmail: string, taId: string): AppUser {
  const actor = requireActor(actorEmail);
  if (atLeastRole(actor.role, "root_admin")) return actor;
  const supervises = loadSupervision().some(
    (link) => link.instructorId === actor.id && link.taId === taId,
  );
  if (!supervises) {
    throw new ApiError(
      403,
      "You can only manage your own teaching assistants.",
    );
  }
  return actor;
}

function validateCheckInput(input: CheckInput) {
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
  actorEmail: string,
  input: CheckInput,
): Promise<SingleCheck> {
  const actor = requireScreeningAccess(actorEmail);
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
    actorId: actor.id,
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
  prependHistory(entry);
  return entry;
}

export async function runBatch(
  actorEmail: string,
  fileName: string,
  inputs: BatchRowInput[],
  strictness: Strictness = "standard",
  onProgress?: (done: number, total: number) => void,
): Promise<BatchRun> {
  const actor = requireScreeningAccess(actorEmail);
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
      actorId: actor.id,
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
  prependHistory(run);
  return run;
}

function ownedBy(entry: HistoryEntry, actorId: string): boolean {
  return entry.kind === "batch"
    ? entry.rows.every((row) => row.actorId === actorId)
    : entry.actorId === actorId;
}

export async function listHistory(
  actorEmail: string,
  signal?: AbortSignal,
): Promise<HistoryEntry[]> {
  await delay(150, signal);
  const actor = requireScreeningAccess(actorEmail);
  return loadHistory().filter((entry) => ownedBy(entry, actor.id));
}

export async function getEntry(
  actorEmail: string,
  id: string,
  signal?: AbortSignal,
): Promise<HistoryEntry | undefined> {
  await delay(120, signal);
  const actor = requireScreeningAccess(actorEmail);
  return loadHistory()
    .filter((entry) => ownedBy(entry, actor.id))
    .find(
      (entry) => (entry.kind === "batch" ? entry.id : entry.checkId) === id,
    );
}

export async function listUsers(
  actorEmail: string,
  signal?: AbortSignal,
): Promise<AppUser[]> {
  await delay(150, signal);
  requireAdmin(actorEmail);
  return loadUsers();
}

export async function listSupervision(
  signal?: AbortSignal,
): Promise<SupervisionLink[]> {
  await delay(80, signal);
  return loadSupervision();
}

function byName(a: AppUser, b: AppUser) {
  return (a.name ?? a.email).localeCompare(b.name ?? b.email);
}

export function supervisorsOf(taId: string): AppUser[] {
  const ids = new Set(
    loadSupervision()
      .filter((link) => link.taId === taId)
      .map((link) => link.instructorId),
  );
  return loadUsers()
    .filter((user) => ids.has(user.id))
    .sort(byName);
}

export function assistantsOf(instructorId: string): AppUser[] {
  const ids = new Set(
    loadSupervision()
      .filter((link) => link.instructorId === instructorId)
      .map((link) => link.taId),
  );
  return loadUsers()
    .filter((user) => ids.has(user.id))
    .sort(byName);
}

export function linkedAt(
  instructorId: string,
  taId: string,
): string | undefined {
  return loadSupervision().find(
    (link) => link.instructorId === instructorId && link.taId === taId,
  )?.createdAt;
}

export async function listMyAssistants(
  actorEmail: string,
  signal?: AbortSignal,
): Promise<AppUser[]> {
  await delay(150, signal);
  const actor = requireActor(actorEmail);
  return assistantsOf(actor.id);
}

export function lookupForLinking(
  actorEmail: string,
  email: string,
): LookupResult {
  requireActor(actorEmail);
  const match = findUserByEmail(email);
  if (!match) return { kind: "free" };
  if (match.role !== "teaching_assistant" || !isActive(match)) {
    return { kind: "not-eligible" };
  }
  return { kind: "linkable", user: match };
}

const SMU_EMAIL = /^[^@\s]+@([a-z]+\.)?smu\.edu\.sg$/i;

export async function createAccount(
  actorEmail: string,
  input: CreateAccountInput,
): Promise<AppUser> {
  await delay(300);
  const actor = requireActor(actorEmail);
  const canCreate =
    input.role === "teaching_assistant"
      ? atLeastRole(actor.role, "instructor")
      : atLeastRole(actor.role, "root_admin");
  if (!canCreate) {
    throw new ApiError(403, "You cannot create an account with that role.");
  }
  if (input.role === "root_admin") {
    throw new ApiError(400, "Admin accounts are seeded, not created here.");
  }

  const email = input.email.trim();
  if (!SMU_EMAIL.test(email)) {
    throw new ApiError(400, "Use an SMU email address.");
  }
  if (findUserByEmail(email)) {
    throw new ApiError(409, "An account already exists for this email.");
  }

  const user: AppUser = {
    id: newId(),
    email,
    name: input.name?.trim() || null,
    role: input.role,
    provisionedBy: actor.id,
    deletedAt: null,
    createdAt: new Date().toISOString(),
  };
  saveUsers([...loadUsers(), user]);

  const supervisors = atLeastRole(actor.role, "root_admin")
    ? (input.supervisorIds ?? [])
    : [actor.id];
  if (input.role === "teaching_assistant" && supervisors.length > 0) {
    const links = loadSupervision();
    const now = new Date().toISOString();
    for (const instructorId of supervisors) {
      links.push({ instructorId, taId: user.id, createdAt: now });
    }
    saveSupervision(links);
  }
  return user;
}

export async function linkSupervision(
  actorEmail: string,
  instructorId: string,
  taId: string,
): Promise<void> {
  await delay(200);
  const actor = requireActor(actorEmail);
  if (!atLeastRole(actor.role, "root_admin") && actor.id !== instructorId) {
    throw new ApiError(
      403,
      "You can only add teaching assistants to yourself.",
    );
  }
  const target = findUserById(taId);
  if (!target) throw new ApiError(404, "That account no longer exists.");
  if (target.role !== "teaching_assistant") {
    throw new ApiError(
      400,
      "Only a teaching assistant account can be supervised.",
    );
  }
  if (!isActive(target)) {
    throw new ApiError(
      409,
      "That account has been deactivated. Contact your administrator.",
    );
  }
  const links = loadSupervision();
  if (
    links.some(
      (link) => link.instructorId === instructorId && link.taId === taId,
    )
  ) {
    return;
  }
  links.push({ instructorId, taId, createdAt: new Date().toISOString() });
  saveSupervision(links);
}

export async function unlinkSupervision(
  actorEmail: string,
  instructorId: string,
  taId: string,
): Promise<void> {
  await delay(200);
  const actor = requireActor(actorEmail);
  if (!atLeastRole(actor.role, "root_admin") && actor.id !== instructorId) {
    throw new ApiError(
      403,
      "You can only remove your own teaching assistants.",
    );
  }
  saveSupervision(
    loadSupervision().filter(
      (link) => !(link.instructorId === instructorId && link.taId === taId),
    ),
  );
}

export async function setUserActive(
  actorEmail: string,
  id: string,
  active: boolean,
): Promise<AppUser> {
  await delay(200);
  const actor = requireAdmin(actorEmail);
  if (actor.id === id) {
    throw new ApiError(403, "You cannot deactivate your own account.");
  }
  const users = loadUsers();
  const user = users.find((candidate) => candidate.id === id);
  if (!user) throw new ApiError(404, "That account no longer exists.");

  user.deletedAt = active ? null : new Date().toISOString();
  saveUsers(users);
  return user;
}

export function strandedBy(instructorId: string): AppUser[] {
  const links = loadSupervision();
  return assistantsOf(instructorId).filter(
    (ta) => links.filter((link) => link.taId === ta.id).length === 1,
  );
}

export async function deactivateInstructor(
  actorEmail: string,
  id: string,
  plan: DeactivationPlan,
): Promise<DeactivationOutcome> {
  await delay(300);
  const actor = requireAdmin(actorEmail);

  if (actor.id === id) {
    throw new ApiError(403, "You cannot deactivate your own account.");
  }

  const stranded = strandedBy(id);
  const outcome: DeactivationOutcome = {
    reassigned: 0,
    deactivated: 0,
    leftUnassigned: 0,
  };

  if (plan.mode === "reassign") {
    const links = loadSupervision();
    const now = new Date().toISOString();
    for (const ta of stranded) {
      links.push({ instructorId: plan.toId, taId: ta.id, createdAt: now });
      outcome.reassigned++;
    }
    saveSupervision(links);
  } else if (plan.mode === "deactivate") {
    const users = loadUsers();
    const now = new Date().toISOString();

    for (const ta of stranded) {
      const account = users.find((candidate) => candidate.id === ta.id);
      if (account && account.id !== actor.id) {
        account.deletedAt = now;
        outcome.deactivated++;
      }
    }
    saveUsers(users);
  } else {
    outcome.leftUnassigned = stranded.length;
  }

  saveSupervision(loadSupervision().filter((link) => link.instructorId !== id));
  await setUserActive(actorEmail, id, false);
  return outcome;
}

export async function resendInvite(
  actorEmail: string,
  id: string,
): Promise<void> {
  await delay(200);
  const user = findUserById(id);
  if (!user) throw new ApiError(404, "That account no longer exists.");
  if (user.role === "teaching_assistant") {
    requireAdminOrSupervisor(actorEmail, id);
  } else {
    requireAdmin(actorEmail);
  }
}
