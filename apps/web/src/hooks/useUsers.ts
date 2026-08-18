import {
  createAccount,
  deactivateInstructor,
  deleteUser,
  listMyAssistants,
  listUsers,
  resendInvite,
  setSupervisor,
  setUserActive,
  userKeys,
} from "../api/users";
import { useAuth } from "./useAuth";
import type { User } from "../api/auth";
import { ApiError } from "../api/client";
import type { CreateAccountInput, DeactivationPlan } from "../types";
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

export function useSetSupervisor() {
  const actor = useActor();
  return useRosterMutation(
    ({ id, supervisorId }: { id: string; supervisorId: string | null }) =>
      setSupervisor(requireActor(actor), id, supervisorId),
  );
}

export function useSetUserActive() {
  const actor = useActor();
  return useRosterMutation(({ id, active }: { id: string; active: boolean }) =>
    setUserActive(requireActor(actor), id, active),
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
