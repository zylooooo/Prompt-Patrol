import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as api from './api'
import type { BatchRowInput, Strictness } from './types'

export function useHistory() {
  return useQuery({ queryKey: ['history'], queryFn: api.listHistory })
}

export function useEntry(id: string | undefined) {
  return useQuery({
    queryKey: ['history', id],
    queryFn: () => api.getEntry(id!),
    enabled: !!id,
  })
}

export function useCheckAnswer() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: api.checkAnswer,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['history'] }),
  })
}

export function useRunBatch(onProgress?: (done: number, total: number) => void) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      fileName,
      rows,
      strictness,
    }: {
      fileName: string
      rows: BatchRowInput[]
      strictness?: Strictness
    }) => api.runBatch(fileName, rows, strictness, onProgress),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['history'] }),
  })
}

// ---- Users and supervision ----

// Any account or link change refetches all the roster caches
function useRosterMutation<TArgs, TResult>(mutationFn: (args: TArgs) => Promise<TResult>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['supervision'] })
      queryClient.invalidateQueries({ queryKey: ['my-assistants'] })
    },
  })
}

export function useUsers() {
  return useQuery({ queryKey: ['users'], queryFn: api.listUsers })
}

export function useSupervision() {
  return useQuery({ queryKey: ['supervision'], queryFn: api.listSupervision })
}

export function useMyAssistants() {
  return useQuery({ queryKey: ['my-assistants'], queryFn: api.listMyAssistants })
}

export function useCreateAccount() {
  return useRosterMutation(api.createAccount)
}

export function useLinkSupervision() {
  return useRosterMutation(({ instructorId, taId }: { instructorId: string; taId: string }) =>
    api.linkSupervision(instructorId, taId),
  )
}

export function useUnlinkSupervision() {
  return useRosterMutation(({ instructorId, taId }: { instructorId: string; taId: string }) =>
    api.unlinkSupervision(instructorId, taId),
  )
}

export function useSetUserActive() {
  return useRosterMutation(({ id, active }: { id: string; active: boolean }) =>
    api.setUserActive(id, active),
  )
}

export function useDeactivateInstructor() {
  return useRosterMutation(({ id, plan }: { id: string; plan: api.DeactivationPlan }) =>
    api.deactivateInstructor(id, plan),
  )
}

// Nothing to reset now that Entra owns credentials. This just confirms the
// account is provisioned so the UI can tell someone to try signing in
export function useResendInvite() {
  return useMutation({ mutationFn: (id: string) => api.resendInvite(id) })
}
