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

const PAGE_LIMIT = 100;

const ROSTER_STATUSES: UserStatus[] = ["active", "deactivated", "deleted"];

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

export const findUserById = stub.findUserById;
export const findUserByEmail = stub.findUserByEmail;
export const supervisorsOf = stub.supervisorsOf;
export const assistantsOf = stub.assistantsOf;
export const linkedAt = stub.linkedAt;
export const strandedBy = stub.strandedBy;

export function lookupForLinking(actor: User, email: string): LookupResult {
  return stub.lookupForLinking(actor, email);
}
