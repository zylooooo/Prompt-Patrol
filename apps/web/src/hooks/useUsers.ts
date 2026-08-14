import {
  createAccount,
  deactivateInstructor,
  linkSupervision,
  listMyAssistants,
  listSupervision,
  listUsers,
  resendInvite,
  setUserActive,
  unlinkSupervision,
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

export function useSupervision() {
  return useQuery({
    queryKey: userKeys.supervision(),
    queryFn: ({ signal }) => listSupervision(signal),
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

export function useLinkSupervision() {
  const actor = useActor();
  return useRosterMutation(
    ({ instructorId, taId }: { instructorId: string; taId: string }) =>
      linkSupervision(requireActor(actor), instructorId, taId),
  );
}

export function useUnlinkSupervision() {
  const actor = useActor();
  return useRosterMutation(
    ({ instructorId, taId }: { instructorId: string; taId: string }) =>
      unlinkSupervision(requireActor(actor), instructorId, taId),
  );
}

export function useSetUserActive() {
  const actor = useActor();
  return useRosterMutation(({ id, active }: { id: string; active: boolean }) =>
    setUserActive(requireActor(actor), id, active),
  );
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
