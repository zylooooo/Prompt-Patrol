import {
  isActive,
  type AppUser,
  type CreateAccountInput,
  type DeactivationOutcome,
  type DeactivationPlan,
  type UserRole,
  type UserStatus,
} from "../types";
import * as stub from "./stub";
import type { User } from "./auth";
import { apiRequest } from "./client";

export const userKeys = {
  all: ["users"] as const,
  list: () => [...userKeys.all, "list"] as const,
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
  return fetchAll({ statuses: ROSTER_STATUSES }, signal);
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

  if (me.role === "instructor") return assistants;
  return assistants.filter((ta) => ta.provisionedBy === me.id);
}

export async function createAccount(
  _actor: User,
  input: CreateAccountInput,
): Promise<AppUser> {
  return toAppUser(
    await apiRequest<UserResponse>(USERS_PATH, {
      method: "POST",
      body: {
        email: input.email.trim(),
        role: input.role,
        display_name: input.name?.trim() || null,
        supervisor_id: input.supervisorId ?? null,
      },
    }),
  );
}

export async function setSupervisor(
  _actor: User,
  id: string,
  supervisorId: string | null,
): Promise<AppUser> {
  return toAppUser(
    await apiRequest<UserResponse>(`${USERS_PATH}${id}/supervisor`, {
      method: "POST",
      body: { supervisor_id: supervisorId },
    }),
  );
}

export async function setUserActive(
  _actor: User,
  id: string,
  active: boolean,
): Promise<AppUser> {
  return toAppUser(
    await apiRequest<UserResponse>(
      `${USERS_PATH}${id}/${active ? "reactivate" : "deactivate"}`,
      { method: "POST" },
    ),
  );
}

export async function listAssistantsOf(
  instructorId: string,
  signal?: AbortSignal,
): Promise<AppUser[]> {
  const assistants = await fetchAll(
    { role: "teaching_assistant", statuses: ASSISTANT_STATUSES },
    signal,
  );
  return assistants.filter((ta) => ta.provisionedBy === instructorId);
}

export async function deactivateInstructor(
  actor: User,
  id: string,
  plan: DeactivationPlan,
): Promise<DeactivationOutcome> {
  const affected = await listAssistantsOf(id);

  const outcome: DeactivationOutcome = {
    reassigned: 0,
    deactivated: 0,
    leftUnassigned: 0,
  };

  if (plan.mode === "reassign") {
    for (const ta of affected) await setSupervisor(actor, ta.id, plan.toId);
    outcome.reassigned = affected.length;
  } else if (plan.mode === "deactivate") {
    for (const ta of affected) {
      if (!isActive(ta)) continue;
      await setUserActive(actor, ta.id, false);
      outcome.deactivated++;
    }
  } else {
    for (const ta of affected) await setSupervisor(actor, ta.id, null);
    outcome.leftUnassigned = affected.length;
  }

  await setUserActive(actor, id, false);
  return outcome;
}

export async function deleteUser(_actor: User, id: string): Promise<AppUser> {
  return toAppUser(
    await apiRequest<UserResponse>(`${USERS_PATH}${id}`, { method: "DELETE" }),
  );
}

export function resendInvite(actor: User, id: string): Promise<void> {
  return stub.resendInvite(actor, id);
}
