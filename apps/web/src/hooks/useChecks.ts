import {
  checkKeys,
  checkAnswer,
  getCapabilities,
  getEntry,
  listHistory,
  runBatch,
} from "../api/checks";
import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useAuth } from "./useAuth";
import type { User } from "../api/auth";
import { ApiError } from "../api/client";
import type { BatchRowInput, CheckInput, Strictness } from "../types";

function useActor(): User | null {
  return useAuth().user;
}

function requireActor(actor: User | null): User {
  if (actor === null) throw new ApiError(401, "You are not signed in.");
  return actor;
}

export const capabilitiesQueryOptions = () =>
  queryOptions({
    queryKey: checkKeys.capabilities(),
    queryFn: ({ signal }) => getCapabilities(signal),
    staleTime: 60 * 60_000,
  });

export function useDetectorCapabilities() {
  return useQuery(capabilitiesQueryOptions());
}

export function useHistory() {
  const actor = useActor();
  return useQuery({
    queryKey: checkKeys.history(),
    queryFn: ({ signal }) => listHistory(requireActor(actor), signal),
    enabled: actor !== null,
  });
}

export function useEntry(id: string | undefined) {
  const actor = useActor();
  return useQuery({
    queryKey: checkKeys.entry(id ?? ""),
    queryFn: ({ signal }) => getEntry(requireActor(actor), id ?? "", signal),
    enabled: actor !== null && id !== undefined,
  });
}

export function useCheckAnswer() {
  const actor = useActor();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CheckInput) => checkAnswer(requireActor(actor), input),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: checkKeys.history() }),
  });
}

export function useRunBatch(
  onProgress?: (done: number, total: number) => void,
) {
  const actor = useActor();
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
    }) => runBatch(requireActor(actor), fileName, rows, strictness, onProgress),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: checkKeys.history() }),
  });
}
