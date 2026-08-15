import { analyseAnswer } from './detector'
import {
  loadHistory,
  loadSupervision,
  loadUsers,
  prependHistory,
  saveSupervision,
  saveUsers,
} from './store'
import {
  ANSWER_MAX_CHARS,
  ANSWER_MIN_CHARS,
  atLeastRole,
  EXTERNAL_REF_MAX_CHARS,
  isActive,
  QUESTION_MAX_CHARS,
  type AppUser,
  type BatchRow,
  type BatchRowInput,
  type BatchRun,
  type HistoryEntry,
  type SingleCheck,
  type Strictness,
  type SupervisionLink,
  type UserRole,
  type Verdict,
} from './types'

// Mock API layer. Every function mirrors a planned backend endpoint so the
// swap to real HTTP calls is mechanical: same names, same shapes.
// This layer also stands in for the server's authorisation, so the permission
// rules live here rather than in the components.
//
// TODO(PP): replace bodies with fetch calls once the users and checks modules
// exist. Auth is already live, so anything auth-related goes through
// /api/auth/* instead of through this file

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function newId(): string {
  return crypto.randomUUID()
}

const sameEmail = (a: string, b: string) => a.toLowerCase() === b.toLowerCase()

// ---- Checks ----

export interface CheckInput {
  answerText: string
  questionText?: string
  externalRef?: string
  strictness?: Strictness
  retainAnswer?: boolean
}

// Same limits the server enforces, checked here so a bad answer fails in the
// form instead of coming back as a 400
function validateCheckInput(input: CheckInput) {
  const answer = input.answerText.trim()
  if (answer.length < ANSWER_MIN_CHARS) {
    throw new Error(`Enter at least ${ANSWER_MIN_CHARS} characters.`)
  }
  if (answer.length > ANSWER_MAX_CHARS) {
    throw new Error(`Answers are limited to ${ANSWER_MAX_CHARS.toLocaleString()} characters.`)
  }
  if (input.questionText && input.questionText.length > QUESTION_MAX_CHARS) {
    throw new Error(`Questions are limited to ${QUESTION_MAX_CHARS.toLocaleString()} characters.`)
  }
  if (input.externalRef && input.externalRef.length > EXTERNAL_REF_MAX_CHARS) {
    throw new Error(`Reference is limited to ${EXTERNAL_REF_MAX_CHARS} characters.`)
  }
}

export async function checkAnswer(input: CheckInput): Promise<SingleCheck> {
  const actor = requireScreeningAccess()
  validateCheckInput(input)
  const startedAt = performance.now()
  await delay(650)

  const strictness = input.strictness ?? 'standard'
  const questionText = input.questionText?.trim() || null
  const analysis = analyseAnswer(input.answerText, strictness, questionText !== null)
  const retain = input.retainAnswer ?? true

  const entry: SingleCheck = {
    kind: 'single',
    checkId: newId(),
    actorId: actor.id,
    batchId: null,
    externalRef: input.externalRef?.trim() || null,
    verdict: analysis.verdict,
    rawScore: analysis.rawScore,
    // stays null until the backend ships calibration
    confidence: null,
    abstainReason: analysis.abstainReason,
    truncated: false,
    detector: analysis.detector,
    answerText: retain ? input.answerText : null,
    questionText,
    explanation: analysis.explanation,
    createdAt: new Date().toISOString(),
    latencyMs: Math.round(performance.now() - startedAt),
  }
  prependHistory(entry)
  return entry
}

export async function runBatch(
  fileName: string,
  inputs: BatchRowInput[],
  strictness: Strictness = 'standard',
  onProgress?: (done: number, total: number) => void,
): Promise<BatchRun> {
  const actor = requireScreeningAccess()
  const batchId = newId()
  const rows: BatchRow[] = []

  for (let i = 0; i < inputs.length; i++) {
    await delay(24)
    const row = inputs[i]
    const questionText = row.questionText?.trim() || null
    const analysis = analyseAnswer(row.answerText, strictness, questionText !== null)
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
    })
    onProgress?.(i + 1, inputs.length)
  }

  const counts: Record<Verdict, number> = { ai_generated: 0, uncertain: 0, human_written: 0 }
  for (const row of rows) counts[row.verdict]++
  // flagged first, then uncertain, then human - highest score first within a group
  const order: Record<Verdict, number> = { ai_generated: 0, uncertain: 1, human_written: 2 }
  rows.sort((a, b) => order[a.verdict] - order[b.verdict] || b.rawScore - a.rawScore)

  const run: BatchRun = {
    id: batchId,
    kind: 'batch',
    fileName,
    createdAt: new Date().toISOString(),
    strictness,
    rows,
    counts,
  }
  prependHistory(run)
  return run
}

// ---- History ----

export async function listHistory(): Promise<HistoryEntry[]> {
  await delay(150)
  requireScreeningAccess()
  return loadHistory()
}

export async function getEntry(id: string): Promise<HistoryEntry | undefined> {
  await delay(120)
  requireScreeningAccess()
  return loadHistory().find((e) => (e.kind === 'batch' ? e.id : e.checkId) === id)
}

// ---- Session and authorisation ----

// The signed-in email, set by AuthProvider after /api/auth/me answers. The
// session itself is an HttpOnly cookie that JavaScript cannot read
let signedInEmail: string | null = null

export function setSignedInEmail(email: string | null) {
  signedInEmail = email
}

// /api/auth/me returns only email and role, so the rest of the account is
// looked up locally. This becomes GET /api/users/me once that module lands
function currentActor(): AppUser | null {
  if (!signedInEmail) return null
  return findUserByEmail(signedInEmail) ?? null
}

function requireActor(): AppUser {
  const actor = currentActor()
  if (!actor) throw new Error('You are not signed in.')
  return actor
}

// Roles are ranked like the backend's require_role, so an admin passes an
// instructor check
function requireRole(min: UserRole): AppUser {
  const actor = requireActor()
  if (!atLeastRole(actor.role, min)) throw new Error('You do not have access to this.')
  return actor
}

const requireAdmin = () => requireRole('root_admin')

// TAs can only screen if an instructor supervises them. Instructors and admins
// always pass. The backend has no supervision table yet, so this gate only
// exists here for now
function requireScreeningAccess(): AppUser {
  const actor = requireActor()
  if (actor.role !== 'teaching_assistant') return actor
  const linked = loadSupervision().some((link) => link.taId === actor.id)
  if (!linked) {
    throw new Error('You are not assigned to an instructor yet, so there is nothing to screen.')
  }
  return actor
}

export function hasScreeningAccess(): boolean {
  try {
    requireScreeningAccess()
    return true
  } catch {
    return false
  }
}

// An instructor may act only on a teaching assistant they supervise
function requireAdminOrSupervisor(taId: string): AppUser {
  const actor = requireActor()
  if (atLeastRole(actor.role, 'root_admin')) return actor
  const supervises = loadSupervision().some(
    (link) => link.instructorId === actor.id && link.taId === taId,
  )
  if (!supervises) throw new Error('You can only manage your own teaching assistants.')
  return actor
}

// ---- Users ----

export async function listUsers(): Promise<AppUser[]> {
  await delay(150)
  requireAdmin()
  return loadUsers()
}

export function findUserById(id: string): AppUser | undefined {
  return loadUsers().find((user) => user.id === id)
}

export function findUserByEmail(email: string): AppUser | undefined {
  return loadUsers().find((user) => sameEmail(user.email, email))
}

export type LookupResult =
  | { kind: 'free' }
  | { kind: 'linkable'; user: AppUser }
  | { kind: 'not-eligible' }

// Only answers "can I add this email as my TA". Every kind of no looks the
// same, so this cannot be used to probe who has an account
export function lookupForLinking(email: string): LookupResult {
  requireActor()
  const match = findUserByEmail(email)
  if (!match) return { kind: 'free' }
  if (match.role !== 'teaching_assistant' || !isActive(match)) return { kind: 'not-eligible' }
  return { kind: 'linkable', user: match }
}

export async function listSupervision(): Promise<SupervisionLink[]> {
  await delay(80)
  return loadSupervision()
}

function byName(a: AppUser, b: AppUser) {
  return (a.name ?? a.email).localeCompare(b.name ?? b.email)
}

export function supervisorsOf(taId: string): AppUser[] {
  const ids = new Set(
    loadSupervision()
      .filter((link) => link.taId === taId)
      .map((link) => link.instructorId),
  )
  return loadUsers()
    .filter((user) => ids.has(user.id))
    .sort(byName)
}

export function assistantsOf(instructorId: string): AppUser[] {
  const ids = new Set(
    loadSupervision()
      .filter((link) => link.instructorId === instructorId)
      .map((link) => link.taId),
  )
  return loadUsers()
    .filter((user) => ids.has(user.id))
    .sort(byName)
}

export function linkedAt(instructorId: string, taId: string): string | undefined {
  return loadSupervision().find(
    (link) => link.instructorId === instructorId && link.taId === taId,
  )?.createdAt
}

// Scoped to the signed-in instructor
export async function listMyAssistants(): Promise<AppUser[]> {
  await delay(150)
  const actor = requireActor()
  return assistantsOf(actor.id)
}

// ---- Account creation ----

const SMU_EMAIL = /^[^@\s]+@([a-z]+\.)?smu\.edu\.sg$/i

function isSmuEmail(email: string): boolean {
  return SMU_EMAIL.test(email.trim())
}

export interface CreateAccountInput {
  email: string
  role: UserRole
  name?: string
  supervisorIds?: string[]
}

// Provisioning only, there is no password to hand out. The account has to
// exist before the person's first Microsoft sign-in, and the email is the
// binding key, so it has to match their SMU account exactly
export async function createAccount(input: CreateAccountInput): Promise<AppUser> {
  await delay(300)
  const actor = requireActor()
  // delegation chain: admins create instructors, instructors create their TAs
  const canCreate =
    input.role === 'teaching_assistant'
      ? atLeastRole(actor.role, 'instructor')
      : atLeastRole(actor.role, 'root_admin')
  if (!canCreate) throw new Error('You cannot create an account with that role.')
  if (input.role === 'root_admin') throw new Error('Admin accounts are seeded, not created here.')

  const email = input.email.trim()
  if (!isSmuEmail(email)) throw new Error('Use an SMU email address.')
  if (findUserByEmail(email)) throw new Error('An account already exists for this email.')

  const user: AppUser = {
    id: newId(),
    email,
    // the users table has no display name column, so this is a local
    // placeholder until first sign-in fills it from the Entra profile
    name: input.name?.trim() || null,
    role: input.role,
    provisionedBy: actor.id,
    deletedAt: null,
    createdAt: new Date().toISOString(),
  }
  saveUsers([...loadUsers(), user])

  const supervisors = atLeastRole(actor.role, 'root_admin') ? (input.supervisorIds ?? []) : [actor.id]
  if (input.role === 'teaching_assistant' && supervisors.length > 0) {
    const links = loadSupervision()
    const now = new Date().toISOString()
    for (const instructorId of supervisors) {
      links.push({ instructorId, taId: user.id, createdAt: now })
    }
    saveSupervision(links)
  }
  return user
}

// ---- Supervision links ----

export async function linkSupervision(instructorId: string, taId: string): Promise<void> {
  await delay(200)
  const actor = requireActor()
  if (!atLeastRole(actor.role, 'root_admin') && actor.id !== instructorId) {
    throw new Error('You can only add teaching assistants to yourself.')
  }
  const target = findUserById(taId)
  if (!target) throw new Error('That account no longer exists.')
  if (target.role !== 'teaching_assistant') {
    throw new Error('Only a teaching assistant account can be supervised.')
  }
  if (!isActive(target)) {
    throw new Error('That account has been deactivated. Contact your administrator.')
  }
  const links = loadSupervision()
  if (links.some((link) => link.instructorId === instructorId && link.taId === taId)) return
  links.push({ instructorId, taId, createdAt: new Date().toISOString() })
  saveSupervision(links)
}

// Removes the link only, never the account
export async function unlinkSupervision(instructorId: string, taId: string): Promise<void> {
  await delay(200)
  const actor = requireActor()
  if (!atLeastRole(actor.role, 'root_admin') && actor.id !== instructorId) {
    throw new Error('You can only remove your own teaching assistants.')
  }
  saveSupervision(
    loadSupervision().filter(
      (link) => !(link.instructorId === instructorId && link.taId === taId),
    ),
  )
}

// ---- Status ----

export async function setUserActive(id: string, active: boolean): Promise<AppUser> {
  await delay(200)
  const actor = requireAdmin()
  if (actor.id === id) throw new Error('You cannot deactivate your own account.')
  const users = loadUsers()
  const user = users.find((candidate) => candidate.id === id)
  if (!user) throw new Error('That account no longer exists.')
  // soft delete the way the users table does it: a timestamp, not a boolean
  user.deletedAt = active ? null : new Date().toISOString()
  saveUsers(users)
  return user
}

// TAs who would lose their only supervisor
export function strandedBy(instructorId: string): AppUser[] {
  const links = loadSupervision()
  return assistantsOf(instructorId).filter(
    (ta) => links.filter((link) => link.taId === ta.id).length === 1,
  )
}

export type DeactivationPlan =
  | { mode: 'reassign'; toId: string }
  | { mode: 'deactivate' }
  | { mode: 'leave' }

export interface DeactivationOutcome {
  reassigned: number
  deactivated: number
  leftUnassigned: number
}

export async function deactivateInstructor(
  id: string,
  plan: DeactivationPlan,
): Promise<DeactivationOutcome> {
  await delay(300)
  const actor = requireAdmin()
  // check before writing anything, so a refusal cannot leave partial changes
  if (actor.id === id) throw new Error('You cannot deactivate your own account.')
  // worked out before any link is removed, since removing them first would
  // destroy the information this needs
  const stranded = strandedBy(id)
  const outcome: DeactivationOutcome = { reassigned: 0, deactivated: 0, leftUnassigned: 0 }

  if (plan.mode === 'reassign') {
    const links = loadSupervision()
    const now = new Date().toISOString()
    for (const ta of stranded) {
      links.push({ instructorId: plan.toId, taId: ta.id, createdAt: now })
      outcome.reassigned++
    }
    saveSupervision(links)
  } else if (plan.mode === 'deactivate') {
    const users = loadUsers()
    const now = new Date().toISOString()
    // this loop deactivates several accounts directly instead of calling
    // setUserActive, so it repeats that function's rules itself.
    // rules: skip records that no longer exist, never deactivate yourself
    for (const ta of stranded) {
      const account = users.find((candidate) => candidate.id === ta.id)
      if (account && account.id !== actor.id) {
        account.deletedAt = now
        outcome.deactivated++
      }
    }
    saveUsers(users)
  } else {
    outcome.leftUnassigned = stranded.length
  }

  // links go, accounts stay
  saveSupervision(loadSupervision().filter((link) => link.instructorId !== id))
  await setUserActive(id, false)
  return outcome
}

// ---- Credentials ----

// Password reset used to live here. No passwords anymore, so all this can do
// is confirm the account exists and that the caller is allowed to ask
export async function resendInvite(id: string): Promise<void> {
  await delay(200)
  const user = findUserById(id)
  if (!user) throw new Error('That account no longer exists.')
  if (user.role === 'teaching_assistant') requireAdminOrSupervisor(id)
  else requireAdmin()
}
