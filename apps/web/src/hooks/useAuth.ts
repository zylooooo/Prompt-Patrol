import { useEffect, useState } from "react";

type User = { email: string; role: string };

export const LOGIN_HINT_KEY = "pp_login_hint";

export function useAuth() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/auth/me", { credentials: "include" })
      .then((res) => (res.ok ? res.json() : null))
      .then((u: User | null) => {
        setUser(u);
        if (u?.email) localStorage.setItem(LOGIN_HINT_KEY, u.email);
      })
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  return { user, loading };
}
