import {
  isActive,
  type AppUser,
  type CreateAccountInput,
  type DeactivationOutcome,
  type DeactivationPlan,
  type UserRole,
  type UserStatus,
} from "../types";
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
  supervisor_ids: string[];
  created_at: string;
  first_login_at: string | null;
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
    supervisorIds: row.supervisor_ids,
    createdAt: row.created_at,
    firstLoginAt: row.first_login_at,
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
  return fetchAll(
    { role: "teaching_assistant", statuses: ASSISTANT_STATUSES },
    signal,
  );
}

export async function createAccount(
  _actor: User,
  input: CreateAccountInput,
): Promise<AppUser> {
  // One request: the server commits the account, the invite and the
  // supervisor link together, or none of them ([0.21.0]).
  return toAppUser(
    await apiRequest<UserResponse>(USERS_PATH, {
      method: "POST",
      body: {
        email: input.email.trim(),
        role: input.role,
        supervisor_id:
          input.role === "teaching_assistant"
            ? (input.supervisorId ?? null)
            : null,
      },
    }),
  );
}

/** Instructor's add-by-email. Created, linked or already there - the server
 * answers the same for all three, on purpose. */
export async function addTeachingAssistant(
  _actor: User,
  email: string,
): Promise<AppUser> {
  return toAppUser(
    await apiRequest<UserResponse>(`${USERS_PATH}teaching-assistants`, {
      method: "POST",
      body: { email: email.trim() },
    }),
  );
}

export async function linkSupervisor(
  _actor: User,
  taId: string,
  instructorId: string,
): Promise<AppUser> {
  return toAppUser(
    await apiRequest<UserResponse>(`${USERS_PATH}${taId}/supervisors`, {
      method: "POST",
      body: { instructor_id: instructorId },
    }),
  );
}

export async function unlinkSupervisor(
  _actor: User,
  taId: string,
  instructorId: string,
): Promise<AppUser> {
  return toAppUser(
    await apiRequest<UserResponse>(
      `${USERS_PATH}${taId}/supervisors/${instructorId}`,
      { method: "DELETE" },
    ),
  );
}

export async function updateDisplayName(
  _actor: User,
  id: string,
  name: string,
): Promise<AppUser> {
  return toAppUser(
    await apiRequest<UserResponse>(`${USERS_PATH}${id}`, {
      method: "PATCH",
      body: { display_name: name.trim() },
    }),
  );
}

export async function changeUserRole(
  _actor: User,
  id: string,
  role: Exclude<UserRole, "root_admin">,
): Promise<AppUser> {
  return toAppUser(
    await apiRequest<UserResponse>(`${USERS_PATH}${id}/role`, {
      method: "PATCH",
      body: { role },
    }),
  );
}

export async function setUserActive(
  _actor: User,
  id: string,
  active: boolean,
  reason?: string,
): Promise<AppUser> {
  return toAppUser(
    await apiRequest<UserResponse>(
      `${USERS_PATH}${id}/${active ? "reactivate" : "deactivate"}`,
      reason ? { method: "POST", body: { reason } } : { method: "POST" },
    ),
  );
}

/** Assistants whose only supervisor is `instructorId`: the ones who can't
 * screen once that instructor is switched off. */
export async function listOnlySupervisedBy(
  instructorId: string,
  signal?: AbortSignal,
): Promise<AppUser[]> {
  const assistants = await fetchAll(
    { role: "teaching_assistant", statuses: ASSISTANT_STATUSES },
    signal,
  );
  return assistants.filter(
    (ta) =>
      ta.supervisorIds.length === 1 && ta.supervisorIds[0] === instructorId,
  );
}

export async function deactivateInstructor(
  actor: User,
  id: string,
  plan: DeactivationPlan,
): Promise<DeactivationOutcome> {
  const affected = await listOnlySupervisedBy(id);

  const outcome: DeactivationOutcome = {
    reassigned: 0,
    deactivated: 0,
    leftUnassigned: 0,
  };

  // Settle the assistants first: if one fails the instructor is still active
  // and the admin can retry from a state they recognise.
  if (plan.mode === "reassign") {
    for (const ta of affected) {
      if (!isActive(ta)) continue; // the server only places active TAs
      await linkSupervisor(actor, ta.id, plan.toId);
      outcome.reassigned++;
    }
  } else if (plan.mode === "deactivate") {
    for (const ta of affected) {
      if (!isActive(ta)) continue;
      await setUserActive(actor, ta.id, false);
      outcome.deactivated++;
    }
  } else {
    // Links are kept and stop counting; reactivating restores the team.
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

export async function resendInvite(_actor: User, id: string): Promise<AppUser> {
  return toAppUser(
    await apiRequest<UserResponse>(`${USERS_PATH}${id}/resend-invite`, {
      method: "POST",
    }),
  );
}
