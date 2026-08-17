// ---------------------------------------------------------------------------
// Supervision does not exist server-side yet: the backend records delegation as
// a single `provisioned_by` column, while every screen here assumes a link table
// a teaching assistant can appear in twice. Those functions stay on ./stub until
// that lands, and the accounts the server returns are mirrored into the stub
// store so a locally-held link points at a real account rather than a seeded
// fiction.
//
// The synchronous exports at the bottom are the other half of the reason this
// is unfinished. They are called during render - see TeachingAssistantsPage and
// RelationshipDialog - so they cannot become requests until those call sites
// become queries.
//
// `_actor` on the functions that reach the server is deliberately unused: the
// session cookie is what tells the API who is asking, and a second, client-
// supplied answer could only ever disagree with it. It stays on the signature
// for the audit logging that has to name an actor, and loses its underscore
// when that arrives.
// ---------------------------------------------------------------------------

import {
  atLeastRole,
  isActive,
  type AppUser,
  type CreateAccountInput,
  type DeactivationOutcome,
  type DeactivationPlan,
  type LookupResult,
  type SupervisionLink,
  type UserRole,
  type UserStatus,
} from "../types";
import * as stub from "./stub";
import type { User } from "./auth";
import { apiRequest } from "./client";

export const userKeys = {
  all: ["users"] as const,
  list: () => [...userKeys.all, "list"] as const,
  supervision: () => [...userKeys.all, "supervision"] as const,
  myAssistants: () => [...userKeys.all, "mine"] as const,
};

const USERS_PATH = "/api/users/";

// One page is the whole roster at this scale, but the endpoint is cursored and
// an admin silently shown the first 50 of 60 accounts has no way to tell.
const PAGE_LIMIT = 200;

// The administrative roster shows removed accounts too - a deleted row is the
// evidence that someone was removed, and the page renders a chip for it. The
// endpoint returns active users only unless asked otherwise, so ask.
const ROSTER_STATUSES: UserStatus[] = ["active", "deactivated", "deleted"];

// A deleted assistant is gone from the delegation screens; a deactivated one is
// still yours, and still reactivatable.
const ASSISTANT_STATUSES: UserStatus[] = ["active", "deactivated"];

interface UserResponse {
  id: string;
  email: string;
  display_name: string | null;
  role: UserRole;
  status: UserStatus;
  provisioned_by: string | null;
  created_at: string;
}

interface UserListResponse {
  items: UserResponse[];
  next_cursor: string | null;
}

function toAppUser(row: UserResponse): AppUser {
  return {
    id: row.id,
    email: row.email,
    name: row.display_name,
    role: row.role,
    status: row.status,
    provisionedBy: row.provisioned_by,
    createdAt: row.created_at,
  };
}

interface ListQuery {
  role?: UserRole;
  statuses: UserStatus[];
}

// Follows the cursor to the end rather than returning a page: every caller here
// filters and counts over the whole set, and a partial answer would read as a
// complete one.
async function fetchAll(
  { role, statuses }: ListQuery,
  signal?: AbortSignal,
): Promise<AppUser[]> {
  const users: AppUser[] = [];
  let cursor: string | null = null;

  do {
    const query = new URLSearchParams({ limit: String(PAGE_LIMIT) });
    if (role) query.set("role", role);
    for (const status of statuses) query.append("status", status);
    if (cursor) query.set("cursor", cursor);

    const page = await apiRequest<UserListResponse>(`${USERS_PATH}?${query}`, {
      signal,
    });
    users.push(...page.items.map(toAppUser));
    cursor = page.next_cursor ?? null;
  } while (cursor !== null);

  return users;
}

export async function getCurrentUser(signal?: AbortSignal): Promise<AppUser> {
  return toAppUser(
    await apiRequest<UserResponse>(`${USERS_PATH}me`, { signal }),
  );
}

export async function listUsers(
  _actor: User,
  signal?: AbortSignal,
): Promise<AppUser[]> {
  const [me, users] = await Promise.all([
    getCurrentUser(signal),
    fetchAll({ statuses: ROSTER_STATUSES }, signal),
  ]);
  // `me` is mirrored alongside the list because an instructor is not in their
  // own scoped listing, and the supervision helpers have to be able to resolve
  // whoever is signed in.
  stub.rememberUsers([me, ...users]);
  return users;
}

export function listSupervision(
  signal?: AbortSignal,
): Promise<SupervisionLink[]> {
  return stub.listSupervision(signal);
}

export async function listMyAssistants(
  _actor: User,
  signal?: AbortSignal,
): Promise<AppUser[]> {
  const [me, assistants] = await Promise.all([
    getCurrentUser(signal),
    fetchAll(
      { role: "teaching_assistant", statuses: ASSISTANT_STATUSES },
      signal,
    ),
  ]);
  stub.rememberUsers([me, ...assistants]);

  // The server scopes an instructor to the assistants they provisioned, which
  // is exactly what this page means by "mine". An admin gets every assistant in
  // the system back instead, so narrow that the way the stub did - by the links
  // - until supervision is something the server knows about.
  if (me.role === "instructor") return assistants;
  const mine = new Set(stub.assistantsOf(me.id).map((ta) => ta.id));
  return assistants.filter((ta) => mine.has(ta.id));
}

export async function createAccount(
  actor: User,
  input: CreateAccountInput,
): Promise<AppUser> {
  const email = input.email.trim();

  const created = toAppUser(
    await apiRequest<UserResponse>(USERS_PATH, {
      method: "POST",
      body: {
        email,
        role: input.role,
        display_name: input.name?.trim() || null,
      },
    }),
  );
  stub.rememberUsers([created]);

  if (created.role === "teaching_assistant") {
    // The server records who provisioned the account and has nowhere to put a
    // second supervisor, so the link table stays local. An instructor may only
    // ever assign themselves; an admin picks from the form.
    const supervisors = atLeastRole(actor.role, "root_admin")
      ? (input.supervisorIds ?? [])
      : [(await getCurrentUser()).id];
    stub.rememberSupervision(supervisors, created.id);
  }

  return created;
}

export function linkSupervision(
  actor: User,
  instructorId: string,
  taId: string,
): Promise<void> {
  return stub.linkSupervision(actor, instructorId, taId);
}

export function unlinkSupervision(
  actor: User,
  instructorId: string,
  taId: string,
): Promise<void> {
  return stub.unlinkSupervision(actor, instructorId, taId);
}

export async function setUserActive(
  _actor: User,
  id: string,
  active: boolean,
): Promise<AppUser> {
  const user = toAppUser(
    await apiRequest<UserResponse>(
      `${USERS_PATH}${id}/${active ? "reactivate" : "deactivate"}`,
      { method: "POST" },
    ),
  );
  stub.rememberUsers([user]);
  return user;
}

export async function deactivateInstructor(
  actor: User,
  id: string,
  plan: DeactivationPlan,
): Promise<DeactivationOutcome> {
  // Two halves, and only one of them is real: what becomes of the assistants
  // this instructor was the sole supervisor of, and the instructor's own
  // status.
  //
  // Their status goes first, because it is the step the server can refuse - an
  // admin aiming this at themselves gets a 403. Doing the bookkeeping first
  // would drop the links and then fail, leaving an active instructor with no
  // assistants.
  const stranded = stub.strandedBy(id);
  await setUserActive(actor, id, false);

  const outcome: DeactivationOutcome = {
    reassigned: 0,
    deactivated: 0,
    leftUnassigned: 0,
  };

  if (plan.mode === "reassign") {
    for (const ta of stranded) stub.rememberSupervision([plan.toId], ta.id);
    outcome.reassigned = stranded.length;
  } else if (plan.mode === "deactivate") {
    for (const ta of stranded) {
      // Already-deactivated assistants would 409: deleted is terminal and
      // deactivated to deactivated is not a transition.
      if (!isActive(ta)) continue;
      await setUserActive(actor, ta.id, false);
      outcome.deactivated++;
    }
  } else {
    outcome.leftUnassigned = stranded.length;
  }

  stub.forgetSupervisionBy(id);
  return outcome;
}

export async function deleteUser(_actor: User, id: string): Promise<AppUser> {
  const user = toAppUser(
    await apiRequest<UserResponse>(`${USERS_PATH}${id}`, { method: "DELETE" }),
  );
  stub.rememberUsers([user]);
  return user;
}

export function resendInvite(actor: User, id: string): Promise<void> {
  return stub.resendInvite(actor, id);
}

// Synchronous, and read during render. They answer out of the mirror above,
// which holds whatever the last roster read returned.
export const findUserById = stub.findUserById;
export const findUserByEmail = stub.findUserByEmail;
export const supervisorsOf = stub.supervisorsOf;
export const assistantsOf = stub.assistantsOf;
export const linkedAt = stub.linkedAt;
export const strandedBy = stub.strandedBy;

// Only ever sees accounts the mirror has, which for an instructor is their own
// assistants. An address belonging to someone else's assistant reads as free
// here and comes back as a 409 from the create call - there is no lookup-by-
// email endpoint to ask instead.
export function lookupForLinking(actor: User, email: string): LookupResult {
  return stub.lookupForLinking(actor, email);
}
