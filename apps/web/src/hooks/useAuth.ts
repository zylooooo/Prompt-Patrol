import {
  authKeys,
  clearPreviousUserData,
  getSession,
  LOGIN_HINT_KEY,
  type SessionState,
} from "../api/auth";
import { useEffect } from "react";
import { subscribeToAuthEvents } from "../lib/authChannel";
import { queryOptions, useQuery, useQueryClient } from "@tanstack/react-query";

export const sessionQueryOptions = () =>
  queryOptions({
    queryKey: authKeys.session(),
    queryFn: ({ signal }) => getSession(signal),
  });

export function useAuth() {
  const queryClient = useQueryClient();
  const {
    data: state,
    isPending,
    isError,
    error,
    refetch,
  } = useQuery(sessionQueryOptions());

  const user = state?.status === "authenticated" ? state.user : null;
  const session = state?.status === "authenticated" ? state.session : null;
  const reason = state?.status === "anonymous" ? state.reason : null;

  useEffect(() => {
    if (!user?.email) return;
    const previous = localStorage.getItem(LOGIN_HINT_KEY);
    if (previous && previous !== user.email) clearPreviousUserData();
    localStorage.setItem(LOGIN_HINT_KEY, user.email);
  }, [user?.email]);

  useEffect(
    () =>
      subscribeToAuthEvents((message) => {
        if (message.type === "session-renewed") {
          queryClient.setQueryData(
            sessionQueryOptions().queryKey,
            (current: SessionState | undefined): SessionState | undefined =>
              current?.status === "authenticated"
                ? {
                    ...current,
                    session: {
                      ...current.session,
                      expiresAt: message.expiresAt,
                    },
                  }
                : current,
          );
          return;
        }
        void queryClient.invalidateQueries({ queryKey: authKeys.session() });
      }),
    [queryClient],
  );

  return { user, session, reason, isPending, isError, error, refetch };
}
