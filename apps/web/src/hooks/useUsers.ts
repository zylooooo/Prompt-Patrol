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
import { ApiError } from "../api/client";
import type { CreateAccountInput, DeactivationPlan } from "../api/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

function useActorEmail(): string | null {
  return useAuth().user?.email ?? null;
}

function requireEmail(email: string | null): string {
  if (email === null) throw new ApiError(401, "You are not signed in.");
  return email;
}

export function useUsers() {
  const email = useActorEmail();
  return useQuery({
    queryKey: userKeys.list(),
    queryFn: ({ signal }) => listUsers(requireEmail(email), signal),
    enabled: email !== null,
  });
}

export function useSupervision() {
  return useQuery({
    queryKey: userKeys.supervision(),
    queryFn: ({ signal }) => listSupervision(signal),
  });
}

export function useMyAssistants() {
  const email = useActorEmail();
  return useQuery({
    queryKey: userKeys.myAssistants(),
    queryFn: ({ signal }) => listMyAssistants(requireEmail(email), signal),
    enabled: email !== null,
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
  const email = useActorEmail();
  return useRosterMutation((input: CreateAccountInput) =>
    createAccount(requireEmail(email), input),
  );
}

export function useLinkSupervision() {
  const email = useActorEmail();
  return useRosterMutation(
    ({ instructorId, taId }: { instructorId: string; taId: string }) =>
      linkSupervision(requireEmail(email), instructorId, taId),
  );
}

export function useUnlinkSupervision() {
  const email = useActorEmail();
  return useRosterMutation(
    ({ instructorId, taId }: { instructorId: string; taId: string }) =>
      unlinkSupervision(requireEmail(email), instructorId, taId),
  );
}

export function useSetUserActive() {
  const email = useActorEmail();
  return useRosterMutation(({ id, active }: { id: string; active: boolean }) =>
    setUserActive(requireEmail(email), id, active),
  );
}

export function useDeactivateInstructor() {
  const email = useActorEmail();
  return useRosterMutation(
    ({ id, plan }: { id: string; plan: DeactivationPlan }) =>
      deactivateInstructor(requireEmail(email), id, plan),
  );
}

export function useResendInvite() {
  const email = useActorEmail();
  return useMutation({
    mutationFn: (id: string) => resendInvite(requireEmail(email), id),
  });
}
