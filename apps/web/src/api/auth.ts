import type { UserRole } from "../types";
import { clearStoredData } from "./stub";
import { ApiError, apiRequest } from "./client";

export interface User {
  email: string;
  role: UserRole;
}

export const LOGIN_HINT_KEY = "pp_login_hint";

export const authKeys = {
  all: ["auth"] as const,
  session: () => [...authKeys.all, "session"] as const,
};

// Drops browser-local data belonging to whoever was signed in before.
export function clearPreviousUserData(): void {
  clearStoredData();
}

// Drops everything this browser holds for the user who is signing out.
export function clearSignedOutState(): void {
  clearPreviousUserData();
  localStorage.removeItem(LOGIN_HINT_KEY);
}

export async function getCurrentUser(
  signal?: AbortSignal,
): Promise<User | null> {
  try {
    return await apiRequest<User>("/api/auth/me", { signal });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}
