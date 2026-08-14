import {
  checkKeys,
  checkAnswer,
  getEntry,
  listHistory,
  runBatch,
} from "../api/checks";
import { useAuth } from "./useAuth";
import { ApiError } from "../api/client";
import type { BatchRowInput, CheckInput, Strictness } from "../api/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

function useActorEmail(): string | null {
  return useAuth().user?.email ?? null;
}

function requireEmail(email: string | null): string {
  if (email === null) throw new ApiError(401, "You are not signed in.");
  return email;
}

export function useHistory() {
  const email = useActorEmail();
  return useQuery({
    queryKey: checkKeys.history(),
    queryFn: ({ signal }) => listHistory(requireEmail(email), signal),
    enabled: email !== null,
  });
}

export function useEntry(id: string | undefined) {
  const email = useActorEmail();
  return useQuery({
    queryKey: checkKeys.entry(id ?? ""),
    queryFn: ({ signal }) => getEntry(requireEmail(email), id ?? "", signal),
    enabled: email !== null && id !== undefined,
  });
}

export function useCheckAnswer() {
  const email = useActorEmail();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CheckInput) => checkAnswer(requireEmail(email), input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: checkKeys.all }),
  });
}

export function useRunBatch(
  onProgress?: (done: number, total: number) => void,
) {
  const email = useActorEmail();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      fileName,
      rows,
      strictness,
    }: {
      fileName: string;
      rows: BatchRowInput[];
      strictness?: Strictness;
    }) => runBatch(requireEmail(email), fileName, rows, strictness, onProgress),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: checkKeys.all }),
  });
}
