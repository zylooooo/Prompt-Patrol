import { useAuth } from "../useAuth";
import type { ReactNode } from "react";
import { LOGIN_HINT_KEY } from "../../api/auth";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The hint doubles as "whose data is in this browser". These cover the handover
 * cases where nobody pressed Sign out: a closed tab, an expired session, or a
 * shared machine the next person just walks up to.
 */

const STUB_KEY = "pp.history.v2";

vi.mock("../../api/auth", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/auth")>("../../api/auth");
  return { ...actual, getSession: vi.fn() };
});

const { getSession } = await import("../../api/auth");
const mockedGetSession = vi.mocked(getSession);

const wrapper = ({ children }: { children: ReactNode }) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

const signedInAs = (email: string) =>
  mockedGetSession.mockResolvedValue({
    status: "authenticated",
    user: { email, role: "instructor" },
    session: {
      expiresAt: Date.now() + 90 * 60_000,
      capped: false,
      idleTimeoutSeconds: 5400,
    },
  });

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});
afterEach(() => localStorage.clear());

describe("useAuth — browser-local data ownership", () => {
  it("drops the previous person's data when a different user signs in", async () => {
    localStorage.setItem(LOGIN_HINT_KEY, "ada@smu.edu.sg");
    localStorage.setItem(STUB_KEY, '["ada history"]');
    signedInAs("grace@smu.edu.sg");

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.user).not.toBeNull());

    expect(localStorage.getItem(STUB_KEY)).toBeNull();
    expect(localStorage.getItem(LOGIN_HINT_KEY)).toBe("grace@smu.edu.sg");
  });

  it("keeps the same person's data across a re-sign-in", async () => {
    localStorage.setItem(LOGIN_HINT_KEY, "ada@smu.edu.sg");
    localStorage.setItem(STUB_KEY, '["ada history"]');
    signedInAs("ada@smu.edu.sg");

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.user).not.toBeNull());

    expect(localStorage.getItem(STUB_KEY)).toBe('["ada history"]');
  });

  it("clears nothing on a first-ever sign-in", async () => {
    localStorage.setItem(STUB_KEY, '["seeded before any login"]');
    signedInAs("ada@smu.edu.sg");

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.user).not.toBeNull());

    expect(localStorage.getItem(STUB_KEY)).toBe('["seeded before any login"]');
    expect(localStorage.getItem(LOGIN_HINT_KEY)).toBe("ada@smu.edu.sg");
  });

  it("leaves storage untouched while signed out", async () => {
    localStorage.setItem(LOGIN_HINT_KEY, "ada@smu.edu.sg");
    localStorage.setItem(STUB_KEY, '["ada history"]');
    mockedGetSession.mockResolvedValue({
      status: "anonymous",
      reason: "session_expired",
    });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isPending).toBe(false));

    expect(localStorage.getItem(STUB_KEY)).toBe('["ada history"]');
    expect(localStorage.getItem(LOGIN_HINT_KEY)).toBe("ada@smu.edu.sg");
  });
});

describe("useAuth — what it reports", () => {
  it("carries the session deadline alongside the user", async () => {
    signedInAs("ada@smu.edu.sg");

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.user).not.toBeNull());

    expect(result.current.session?.expiresAt).toBeGreaterThan(Date.now());
    expect(result.current.reason).toBeNull();
  });

  it("surfaces why nobody is signed in", async () => {
    // Without this the app can only ever guess, and it used to guess
    // "your session timed out" for every cause including a deactivated account.
    mockedGetSession.mockResolvedValue({
      status: "anonymous",
      reason: "account_deactivated",
    });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isPending).toBe(false));

    expect(result.current.user).toBeNull();
    expect(result.current.reason).toBe("account_deactivated");
  });
});
