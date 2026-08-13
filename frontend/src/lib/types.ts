// Shapes mirror the backend contract in docs/openapi.yaml and the models in
// apps/api/app/models. The API talks snake_case, this app talks camelCase, and
// api.ts is the only place that translates between them

// ---- Checks ----

// Machine values from the API. Wording lives in VERDICT_TEXT below, so the
// backend never ships display copy and rewording is never a contract change
export type Verdict = 'ai_generated' | 'human_written' | 'uncertain'

export const VERDICT_TEXT: Record<Verdict, string> = {
  ai_generated: 'Likely AI-generated',
  uncertain: 'Uncertain',
  human_written: 'Likely human',
}

// The client sends a named level, never a number. The server owns the
// threshold because score scales change with every model swap
export type Strictness = 'lenient' | 'standard' | 'strict'

export const STRICTNESS_TEXT: Record<Strictness, string> = {
  lenient: 'Lenient',
  standard: 'Standard',
  strict: 'Strict',
}

// Target false positive rates from the strictness table in the spec. Provisional
// until calibration lands, which is why they live next to the copy and not in
// the scoring code
export const STRICTNESS_HINT: Record<Strictness, string> = {
  lenient: 'Flags more answers, about 5 in 100 flagged in error',
  standard: 'Flags about 1 in 100 in error',
  strict: 'Flags only high-confidence cases, about 1 in 1000 in error',
}

// Only set when the verdict is uncertain. Explains why the tool declined to call it
export type AbstainReason = 'answer_too_short' | 'low_signal' | 'score_in_abstention_band' | null

export const ABSTAIN_TEXT: Record<NonNullable<AbstainReason>, string> = {
  answer_too_short: 'The answer is too short to judge.',
  low_signal: 'The writing carries too little signal either way.',
  score_in_abstention_band: 'The score sits too close to the flag threshold to call.',
}

// Codes rather than sentences, same reason as the verdict: the wording lives
// in CUE_TEXT. The contract leaves explanation's shape open on purpose
export type CueCode =
  | 'formal_vocabulary'
  | 'uniform_sentence_length'
  | 'long_sentences'
  | 'informal_phrasing'
  | 'short_answer'

export const CUE_TEXT: Record<CueCode, string> = {
  formal_vocabulary: 'Vocabulary is more formal than typical short answers.',
  uniform_sentence_length: 'Sentence lengths are unusually uniform.',
  long_sentences: 'Sentences are long and densely constructed.',
  informal_phrasing: 'Informal phrasing lowers the likelihood of AI generation.',
  short_answer: 'Answer is short, so the signal is weak.',
}

export interface Explanation {
  cues: CueCode[]
}

// Which model and operating point produced a verdict. Kept per result so an old
// check stays interpretable after the model or calibration changes
export interface DetectorInfo {
  modelVersion: string
  calibrationVersion: string | null
  strictnessApplied: Strictness
  thresholdApplied: number | null
  targetFpr: number | null
  usedQuestionText: boolean
}

// Input limits from CheckCreateRequest. Enforced here so a bad answer fails in
// the form instead of as a 400 from the server
export const ANSWER_MIN_CHARS = 10
export const ANSWER_MAX_CHARS = 10000
export const QUESTION_MAX_CHARS = 2000
export const EXTERNAL_REF_MAX_CHARS = 128

// One check. The same shape covers a single answer and a batch row, which is
// why both render with the same components. The nullable fields really can be
// null, confidence needs calibration that does not exist yet
export interface CheckResult {
  checkId: string
  actorId: string
  batchId: string | null
  externalRef: string | null
  verdict: Verdict
  // 0 to 1, higher means more AI-like. Not a probability, so never render it
  // as a percentage
  rawScore: number
  // calibrated and safe to show, but null until calibration ships
  confidence: number | null
  abstainReason: AbstainReason
  truncated: boolean | null
  detector: DetectorInfo
  // null when the instructor chose not to retain the answer
  answerText: string | null
  questionText: string | null
  explanation: Explanation | null
  createdAt: string
  latencyMs: number | null
}

// What GET /api/detector reports on startup. The question input and the CSV
// validator both read requiresQuestionText rather than hardcoding it
export interface DetectorCapabilities {
  modelVersion: string
  requiresQuestionText: boolean
  minAnswerChars: number
  maxAnswerChars: number
  strictnessLevels: Strictness[]
  supportsExplanation: boolean
  supportsSpans: boolean
}

// ---- Batches ----

// Local grouping for now. The batches module is not built yet, and when it is
// it will be submit-then-poll rather than a single call
export interface BatchRowInput {
  externalRef: string
  answerText: string
  questionText?: string
}

export type BatchRow = CheckResult

export interface BatchRun {
  id: string
  kind: 'batch'
  fileName: string
  createdAt: string
  strictness: Strictness
  rows: BatchRow[]
  counts: Record<Verdict, number>
}

export interface SingleCheck extends CheckResult {
  kind: 'single'
}

export type HistoryEntry = SingleCheck | BatchRun

// A batch is identified by its run id, a single check by its check id. One
// helper so history routing does not have to branch everywhere
export function entryId(entry: HistoryEntry): string {
  return entry.kind === 'batch' ? entry.id : entry.checkId
}

// ---- Users ----

// Matches UserRoleEnum in apps/api/app/models/user.py. root_admin is a role of
// its own, not a flag on top of another role
export type UserRole = 'root_admin' | 'instructor' | 'teaching_assistant'

export const ROLE_TEXT: Record<UserRole, string> = {
  root_admin: 'Admin',
  instructor: 'Instructor',
  teaching_assistant: 'Teaching assistant',
}

// Same ranking the backend uses in auth/dependencies.py, so a check here means
// the same thing a require_role check means there
const ROLE_ORDER: Record<UserRole, number> = {
  teaching_assistant: 0,
  instructor: 1,
  root_admin: 2,
}

export function atLeastRole(role: UserRole, min: UserRole): boolean {
  return ROLE_ORDER[role] >= ROLE_ORDER[min]
}

// Mirrors the users table. No display_name column exists yet, so name is a
// local placeholder and the email is the fallback
export interface AppUser {
  id: string
  email: string
  name: string | null
  role: UserRole
  provisionedBy: string | null
  // soft delete: null means the account is active
  deletedAt: string | null
  createdAt: string
}

export function isActive(user: AppUser): boolean {
  return user.deletedAt === null
}

export function displayName(user: AppUser): string {
  return user.name ?? user.email.split('@')[0]
}

export function roleLabel(user: AppUser): string {
  return ROLE_TEXT[user.role]
}

// Frontend-only for now. The backend records a single provisioned_by, so shared
// supervision has no server side yet
export interface SupervisionLink {
  instructorId: string
  taId: string
  createdAt: string
}
