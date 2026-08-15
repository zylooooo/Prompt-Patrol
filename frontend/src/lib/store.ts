import type { AppUser, HistoryEntry, SupervisionLink } from './types'

// All three keys moved to v2 when the shapes changed to match the backend:
// users are keyed by uuid now, supervision links reference ids, and checks
// carry verdicts instead of labels. Bumping the key orphans the old data
// instead of crashing on it
const HISTORY_KEY = 'pp.history.v2'
const USERS_KEY = 'pp.users.v2'
const SUPERVISION_KEY = 'pp.supervision.v2'
const HISTORY_CAP = 200

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown) {
  localStorage.setItem(key, JSON.stringify(value))
}

export function loadHistory(): HistoryEntry[] {
  return readJson<HistoryEntry[]>(HISTORY_KEY, [])
}

export function prependHistory(entry: HistoryEntry) {
  // localStorage has a ~5MB quota and batch runs are large. If
  // the write fails, drop the oldest half and retry
  let list = [entry, ...loadHistory()].slice(0, HISTORY_CAP)
  while (true) {
    try {
      writeJson(HISTORY_KEY, list)
      return
    } catch {
      if (list.length > 1) {
        list = list.slice(0, Math.ceil(list.length / 2))
      } else {
        throw new Error('History storage is full. Clear old browser site data to free space.')
      }
    }
  }
}

const T0 = '2026-07-01T00:00:00.000Z'
const T1 = '2026-07-08T04:00:00.000Z'
const T2 = '2026-07-09T02:00:00.000Z'

// Fixed uuids so the links between seed rows stay valid across reloads. Real
// ones come from Postgres
const ID_ADMIN = '00000000-0000-4000-8000-000000000001'
const ID_DON = '00000000-0000-4000-8000-000000000002'
const ID_JANE = '00000000-0000-4000-8000-000000000003'
const ID_ALEX = '00000000-0000-4000-8000-000000000004'
const ID_MEI = '00000000-0000-4000-8000-000000000005'
const ID_SARA = '00000000-0000-4000-8000-000000000006'
const ID_RAJ = '00000000-0000-4000-8000-000000000007'

// provisionedBy follows the delegation chain: the seeded admin creates
// instructors, and instructors create their own TAs
const SEED_USERS: AppUser[] = [
  { id: ID_ADMIN, email: 'admin@smu.edu.sg', name: 'Root Admin', role: 'root_admin', provisionedBy: null, deletedAt: null, createdAt: T0 },
  { id: ID_DON, email: 'donta@smu.edu.sg', name: 'Dr. Don Ta', role: 'instructor', provisionedBy: ID_ADMIN, deletedAt: null, createdAt: T0 },
  { id: ID_JANE, email: 'janetan@smu.edu.sg', name: 'Dr. Jane Tan', role: 'instructor', provisionedBy: ID_ADMIN, deletedAt: null, createdAt: T1 },
  { id: ID_ALEX, email: 'alexlim@smu.edu.sg', name: 'Alex Lim', role: 'teaching_assistant', provisionedBy: ID_DON, deletedAt: null, createdAt: T1 },
  { id: ID_MEI, email: 'meichen@smu.edu.sg', name: 'Mei Chen', role: 'teaching_assistant', provisionedBy: ID_DON, deletedAt: null, createdAt: T1 },
  { id: ID_SARA, email: 'sarang@smu.edu.sg', name: 'Sara Ng', role: 'teaching_assistant', provisionedBy: ID_JANE, deletedAt: null, createdAt: T2 },
  { id: ID_RAJ, email: 'rajmenon@smu.edu.sg', name: 'Raj Menon', role: 'teaching_assistant', provisionedBy: ID_JANE, deletedAt: null, createdAt: T2 },
]

// Mei has 2 supervisors. Raj starts unassigned to test the empty state
const SEED_SUPERVISION: SupervisionLink[] = [
  { instructorId: ID_DON, taId: ID_ALEX, createdAt: T1 },
  { instructorId: ID_DON, taId: ID_MEI, createdAt: T1 },
  { instructorId: ID_JANE, taId: ID_MEI, createdAt: T1 },
  { instructorId: ID_JANE, taId: ID_SARA, createdAt: T2 },
]

export function loadUsers(): AppUser[] {
  const users = readJson<AppUser[]>(USERS_KEY, [])
  if (users.length === 0) {
    writeJson(USERS_KEY, SEED_USERS)
    return SEED_USERS
  }
  return users
}

export function saveUsers(users: AppUser[]) {
  writeJson(USERS_KEY, users)
}

export function loadSupervision(): SupervisionLink[] {
  const raw = localStorage.getItem(SUPERVISION_KEY)
  if (raw === null) {
    writeJson(SUPERVISION_KEY, SEED_SUPERVISION)
    return SEED_SUPERVISION
  }
  return readJson<SupervisionLink[]>(SUPERVISION_KEY, [])
}

export function saveSupervision(links: SupervisionLink[]) {
  writeJson(SUPERVISION_KEY, links)
}
