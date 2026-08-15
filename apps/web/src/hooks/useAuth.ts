import { useEffect } from "react";
import { getCurrentUser, authKeys } from "../api/auth";
import { queryOptions, useQuery } from "@tanstack/react-query";

export const LOGIN_HINT_KEY = "pp_login_hint";

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
  } = useQuery(sessionQueryOptions());

  useEffect(() => {
    if (user?.email) localStorage.setItem(LOGIN_HINT_KEY, user.email);
  }, [user?.email]);

  return { user: user ?? null, isPending, isError, error };
}
