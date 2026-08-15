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
  return { ...actual, getCurrentUser: vi.fn() };
});

const { getCurrentUser } = await import("../../api/auth");
const mockedGetCurrentUser = vi.mocked(getCurrentUser);

const wrapper = ({ children }: { children: ReactNode }) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

const signedInAs = (email: string) =>
  mockedGetCurrentUser.mockResolvedValue({ email, role: "instructor" });

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
    mockedGetCurrentUser.mockResolvedValue(null);

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.isPending).toBe(false));

    expect(localStorage.getItem(STUB_KEY)).toBe('["ada history"]');
    expect(localStorage.getItem(LOGIN_HINT_KEY)).toBe("ada@smu.edu.sg");
  });
});
