import {
  addTeachingAssistant,
  changeUserRole,
  createAccount,
  deactivateInstructor,
  deleteUser,
  linkSupervisor,
  listMyAssistants,
  listUsers,
  resendInvite,
  setUserActive,
  unlinkSupervisor,
  updateDisplayName,
  userKeys,
} from "../api/users";
import { useAuth } from "./useAuth";
import { authKeys, type User } from "../api/auth";
import { ApiError } from "../api/client";
import type { CreateAccountInput, DeactivationPlan, UserRole } from "../types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

function useActor(): User | null {
  return useAuth().user;
}

function requireActor(actor: User | null): User {
  if (actor === null) throw new ApiError(401, "You are not signed in.");
  return actor;
}

export function useUsers() {
  const actor = useActor();
  return useQuery({
    queryKey: userKeys.list(),
    queryFn: ({ signal }) => listUsers(requireActor(actor), signal),
    enabled: actor !== null,
  });
}

export function useMyAssistants() {
  const actor = useActor();
  return useQuery({
    queryKey: userKeys.myAssistants(),
    queryFn: ({ signal }) => listMyAssistants(requireActor(actor), signal),
    enabled: actor !== null,
  });
}

function useRosterMutation<TArgs, TResult>(
  mutationFn: (args: TArgs) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: userKeys.all }),
  });
}

export function useCreateAccount() {
  const actor = useActor();
  return useRosterMutation((input: CreateAccountInput) =>
    createAccount(requireActor(actor), input),
  );
}

export function useAddTeachingAssistant() {
  const actor = useActor();
  return useRosterMutation((email: string) =>
    addTeachingAssistant(requireActor(actor), email),
  );
}

interface LinkArgs {
  taId: string;
  instructorId: string;
}

export function useLinkSupervisor() {
  const actor = useActor();
  return useRosterMutation(({ taId, instructorId }: LinkArgs) =>
    linkSupervisor(requireActor(actor), taId, instructorId),
  );
}

export function useUnlinkSupervisor() {
  const actor = useActor();
  return useRosterMutation(({ taId, instructorId }: LinkArgs) =>
    unlinkSupervisor(requireActor(actor), taId, instructorId),
  );
}

/** Also refreshes the session: the shell and the first-sign-in gate read the
 * signed-in person's name from it. */
export function useUpdateDisplayName() {
  const actor = useActor();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      updateDisplayName(requireActor(actor), id, name),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: userKeys.all }),
        queryClient.invalidateQueries({ queryKey: authKeys.session() }),
      ]),
  });
}

export function useChangeUserRole() {
  const actor = useActor();
  return useRosterMutation(
    ({ id, role }: { id: string; role: Exclude<UserRole, "root_admin"> }) =>
      changeUserRole(requireActor(actor), id, role),
  );
}

export function useSetUserActive() {
  const actor = useActor();
  return useRosterMutation(
    ({
      id,
      active,
      reason,
    }: {
      id: string;
      active: boolean;
      reason?: string;
    }) => setUserActive(requireActor(actor), id, active, reason),
  );
}

export function useDeleteUser() {
  const actor = useActor();
  return useRosterMutation((id: string) => deleteUser(requireActor(actor), id));
}

export function useDeactivateInstructor() {
  const actor = useActor();
  return useRosterMutation(
    ({ id, plan }: { id: string; plan: DeactivationPlan }) =>
      deactivateInstructor(requireActor(actor), id, plan),
  );
}

export function useResendInvite() {
  const actor = useActor();
  return useMutation({
    mutationFn: (id: string) => resendInvite(requireActor(actor), id),
  });
}
