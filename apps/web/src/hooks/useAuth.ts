import {
  authKeys,
  clearPreviousUserData,
  getCurrentUser,
  LOGIN_HINT_KEY,
} from "../api/auth";
import { useEffect } from "react";
import { queryOptions, useQuery } from "@tanstack/react-query";

export const sessionQueryOptions = () =>
  queryOptions({
    queryKey: authKeys.session(),
    queryFn: ({ signal }) => getCurrentUser(signal),
  });

export function useAuth() {
  const {
    data: user,
    isPending,
    isError,
    error,
    refetch,
  } = useQuery(sessionQueryOptions());

  useEffect(() => {
    if (!user?.email) return;
    const previous = localStorage.getItem(LOGIN_HINT_KEY);
    if (previous && previous !== user.email) clearPreviousUserData();
    localStorage.setItem(LOGIN_HINT_KEY, user.email);
  }, [user?.email]);

  return { user: user ?? null, isPending, isError, error, refetch };
}
