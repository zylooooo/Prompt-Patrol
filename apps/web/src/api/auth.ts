import type { UserRole } from "../types";
import { clearStoredData } from "./stub";
import { ApiError, apiRequest } from "./client";

export interface User {
  email: string;
  role: UserRole;
}

export interface SessionInfo {
  expiresAt: number;
  capped: boolean;
  idleTimeoutSeconds: number;
}

export type SignedOutReason =
  | "not_signed_in"
  | "session_unknown"
  | "session_revoked"
  | "session_expired"
  | "session_ended"
  | "account_deactivated"
  | "signed_out";

export type SessionState =
  | { status: "authenticated"; user: User; session: SessionInfo }
  | { status: "anonymous"; reason: SignedOutReason };

export const LOGIN_HINT_KEY = "pp_login_hint";
const SIGNED_OUT_KEY = "pp_signed_out";

export const authKeys = {
  all: ["auth"] as const,
  session: () => [...authKeys.all, "session"] as const,
};

export function hadSignedInSession(): boolean {
  return localStorage.getItem(LOGIN_HINT_KEY) !== null;
}

export function clearPreviousUserData(): void {
  clearStoredData();
}

export function clearSignedOutState(): void {
  clearPreviousUserData();
  localStorage.removeItem(LOGIN_HINT_KEY);
}

export function beginSignOut(): void {
  clearSignedOutState();
  try {
    sessionStorage.setItem(SIGNED_OUT_KEY, "1");
  } catch {}
}

export function consumeSignOutMarker(): boolean {
  try {
    const present = sessionStorage.getItem(SIGNED_OUT_KEY) !== null;
    if (present) sessionStorage.removeItem(SIGNED_OUT_KEY);
    return present;
  } catch {
    return false;
  }
}

const SIGNED_OUT_REASONS = new Set<string>([
  "not_signed_in",
  "session_unknown",
  "session_revoked",
  "session_expired",
  "session_ended",
  "account_deactivated",
]);

interface MeResponse {
  email: string;
  role: UserRole;
  session: {
    expires_in_seconds: number;
    capped: boolean;
    idle_timeout_seconds: number;
  };
}

function reasonFrom(error: ApiError): SignedOutReason {
  if (error.code && SIGNED_OUT_REASONS.has(error.code)) {
    if (error.code === "not_signed_in") {
      return hadSignedInSession() ? "signed_out" : "not_signed_in";
    }
    return error.code as SignedOutReason;
  }
  return "not_signed_in";
}

export interface SessionReadOptions {
  probe?: boolean;
}

export async function getSession(
  signal?: AbortSignal,
  { probe = false }: SessionReadOptions = {},
): Promise<SessionState> {
  try {
    const body = await apiRequest<MeResponse>(
      probe ? "/api/auth/me?probe=1" : "/api/auth/me",
      { signal },
    );
    return {
      status: "authenticated",
      user: { email: body.email, role: body.role },
      session: {
        expiresAt: Date.now() + body.session.expires_in_seconds * 1000,
        capped: body.session.capped,
        idleTimeoutSeconds: body.session.idle_timeout_seconds,
      },
    };
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return { status: "anonymous", reason: reasonFrom(error) };
    }
    throw error;
  }
}
