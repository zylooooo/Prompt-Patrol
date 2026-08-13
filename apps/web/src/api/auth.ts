import { ApiError, apiRequest } from "./client";

export interface User {
  email: string;
  role: string;
}

export interface DevUser {
  email: string;
  role: string;
}

export interface DevAuthInfo {
  entra_configured: boolean;
  users: DevUser[];
}

export const authKeys = {
  all: ["auth"] as const,
  session: () => [...authKeys.all, "session"] as const,
  devAuth: () => [...authKeys.all, "dev"] as const,
};

// Function to retrieve the signed-in user, or 'null' if there is no session found.
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

// Function to retrieve provisioned accounts and check if Entra is configured for that account.
export async function getDevAuthInfo(
  signal?: AbortSignal,
): Promise<DevAuthInfo | null> {
  try {
    return await apiRequest<DevAuthInfo>("/api/auth/dev/users", { signal });
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

// Issues a session for an already-provisioned account (for development environment builds only)
export async function devLogin(email: string): Promise<void> {
  await apiRequest<void>("/api/auth/dev/login", {
    method: "POST",
    body: { email },
  });
}
