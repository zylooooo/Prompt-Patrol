import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { checkKeys } from "../api/checks";
import { useAuth } from "./useAuth";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  cancelBatch,
  createBatch,
  getBatchProgress,
  requestUploadUrl,
  uploadFileToS3,
} from "../api/batches";
import type { CreateBatchInput } from "../api/batches";
import {
  clearActiveBatch as clearActiveBatchStorage,
  readActiveBatch,
  writeActiveBatch,
  type ActiveBatch,
} from "../lib/activeBatch";

const PROGRESS_POLL_MS = 2_000;
const progressKey = (batchId: string) => ["batches", "progress", batchId] as const;

// Tracks the one batch a user has in flight so a page refresh or nav away
// mid-run doesn't lose the ability to find it again - see the "resume/track
// an in-progress batch" gap. Keyed by email in localStorage since `User`
// carries no id (see api/auth.ts).
export function useActiveBatch() {
  const { user } = useAuth();
  const email = user?.email ?? null;
  const [active, setActive] = useState<ActiveBatch | null>(() =>
    email ? readActiveBatch(email) : null,
  );

  const save = useCallback(
    (batch: Omit<ActiveBatch, "email">) => {
      if (!email) return;
      const record: ActiveBatch = { ...batch, email };
      writeActiveBatch(record);
      setActive(record);
    },
    [email],
  );

  const clear = useCallback(() => {
    clearActiveBatchStorage();
    setActive(null);
  }, []);

  // Memoized so callers can depend on the whole object in a useEffect deps
  // array (satisfies exhaustive-deps) without it changing identity - and
  // therefore re-running the effect - on every unrelated render.
  return useMemo(() => ({ active, save, clear }), [active, save, clear]);
}

export function useCreateBatch() {
  return useMutation({
    mutationFn: async ({ file, input }: { file: File; input: CreateBatchInput }) => {
      const { uploadUrl, uploadKey } = await requestUploadUrl(input.fileName);
      await uploadFileToS3(uploadUrl, file);
      return createBatch(uploadKey, input);
    },
  });
}

export function useBatchProgress(batchId: string | null) {
  const queryClient = useQueryClient();
  // Only the completed/failed count moving is worth an invalidation - the
  // interval callback fires on every poll tick regardless of whether
  // anything changed, and listHistory() walks every history page, so
  // invalidating unconditionally re-fetched the whole history on every tick.
  const lastResolved = useRef<number | null>(null);
  return useQuery({
    queryKey: progressKey(batchId ?? ""),
    queryFn: ({ signal }) => getBatchProgress(batchId as string, signal),
    enabled: batchId !== null,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return PROGRESS_POLL_MS;
      const resolved = data.completed + data.failed;
      if (resolved !== lastResolved.current) {
        lastResolved.current = resolved;
        void queryClient.invalidateQueries({ queryKey: checkKeys.history() });
      }
      const done = data.cancelled || resolved >= data.rowTotal;
      return done ? false : PROGRESS_POLL_MS;
    },
  });
}

export function useCancelBatch(batchId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => cancelBatch(batchId as string),
    onSuccess: (progress) => {
      if (batchId) queryClient.setQueryData(progressKey(batchId), progress);
      void queryClient.invalidateQueries({ queryKey: checkKeys.history() });
    },
  });
}
