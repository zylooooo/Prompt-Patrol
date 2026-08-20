import type { ReactNode } from "react";
import { ApiError } from "../../api/client";
import type { UserRole } from "../../types";
import { ProtectedRoute } from "../ProtectedRoute";
import userEvent from "@testing-library/user-event";
import { act, cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

const useAuthMock = vi.fn();
vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => useAuthMock() as unknown,
}));

const refetch = vi.fn();

const pendingAuth = {
  user: null,
  session: null,
  reason: null,
  isPending: true,
  isError: false,
  error: null,
  refetch,
};

const signedIn = (user: unknown) => ({
  ...pendingAuth,
  user,
  isPending: false,
});

const signedOut = (reason: string | null) => ({
  ...pendingAuth,
  reason,
  isPending: false,
});

const failed = (error: unknown) => ({
  ...pendingAuth,
  isPending: false,
  isError: true,
  error,
});

function renderGuarded(children: ReactNode = <p>protected content</p>) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/check"]}>
        <Routes>
          <Route
            path="/check"
            element={<ProtectedRoute>{children}</ProtectedRoute>}
          />
          <Route path="/login" element={<LoginProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function LoginProbe() {
  const reason = new URLSearchParams(useLocation().search).get("error");
  return <p data-testid="login">login:{reason ?? "no-reason"}</p>;
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.useRealTimers();
});

describe("ProtectedRoute", () => {
  it("renders the route when a session resolves", () => {
    useAuthMock.mockReturnValue(
      signedIn({ email: "ada@smu.edu.sg", role: "instructor" }),
    );

    renderGuarded();

    expect(screen.getByText("protected content")).toBeDefined();
  });

  it("renders nothing for a session check that answers promptly", () => {
    vi.useFakeTimers();
    useAuthMock.mockReturnValue(pendingAuth);

    const { container } = renderGuarded();
    act(() => void vi.advanceTimersByTime(200));

    expect(container.textContent).toBe("");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows a labelled spinner once the check is visibly slow", () => {
    vi.useFakeTimers();
    useAuthMock.mockReturnValue(pendingAuth);

    renderGuarded();
    act(() => void vi.advanceTimersByTime(250));

    expect(screen.getByRole("status").textContent).toContain(
      "Checking your session",
    );
    expect(screen.queryByTestId("login")).toBeNull();
  });

  it.each([
    "session_expired",
    "session_ended",
    "session_revoked",
    "session_unknown",
    "account_deactivated",
    "signed_out",
  ])("carries the server's reason (%s) to the login page", (reason) => {
    // Each of these used to arrive as an identical opaque 401 and be reported
    // as "your session timed out", which for most of them is simply untrue.
    useAuthMock.mockReturnValue(signedOut(reason));

    renderGuarded();

    expect(screen.getByTestId("login").textContent).toBe(`login:${reason}`);
  });

  it("blames nothing on a first visit", () => {
    // "not_signed_in" is not a thing that happened to the user - they have not
    // been signed out of anything, so the login page must stay quiet.
    useAuthMock.mockReturnValue(signedOut("not_signed_in"));

    renderGuarded();

    expect(screen.getByTestId("login").textContent).toBe("login:no-reason");
  });

  it("says the server is unreachable instead of claiming a sign-out", async () => {
    // The whole point: a failed session check is not an answer about who the
    // user is. Sending them to /login states, wrongly, that they are signed
    // out - and the sign-in they would then attempt runs through the same dead
    // backend, so an outage reads as a broken account.
    useAuthMock.mockReturnValue(
      failed(new ApiError(0, "Could not reach the server.")),
    );

    renderGuarded();

    expect(screen.queryByTestId("login")).toBeNull();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Can't reach Prompt Patrol");
    expect(alert.textContent).toContain("have not been signed out");

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("reads a dead backend behind the proxy as unreachable too", () => {
    // Confirmed against the running stack: stopping the API container makes
    // /api/auth/me return 502 through Vite, not a failed connection. Treating
    // that as an application error told the user the server had answered when
    // nothing was running.
    useAuthMock.mockReturnValue(failed(new ApiError(502, "Bad Gateway")));

    renderGuarded();

    expect(screen.getByRole("alert").textContent).toContain(
      "Can't reach Prompt Patrol",
    );
  });

  it("does not blame the network for a server-side failure", () => {
    // A 500 is the app answering badly, not an outage the user can fix by
    // checking their wifi. Telling them it is sends them chasing the wrong thing.
    useAuthMock.mockReturnValue(failed(new ApiError(500, "boom")));

    renderGuarded();

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Prompt Patrol is having a problem");
    expect(alert.textContent).toContain("have not been signed out");
  });
});

describe("ProtectedRoute — role gating", () => {
  function renderRoleGated(roles: UserRole[]) {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    return render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/teaching-assistants"]}>
          <Routes>
            <Route
              path="/teaching-assistants"
              element={
                <ProtectedRoute roles={roles}>
                  <p>assistants</p>
                </ProtectedRoute>
              }
            />
            <Route path="/" element={<p data-testid="home">home</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  const as = (role: UserRole) =>
    useAuthMock.mockReturnValue(signedIn({ email: "ada@smu.edu.sg", role }));

  it("renders the page for a role on the list", () => {
    as("instructor");

    renderRoleGated(["instructor"]);

    expect(screen.getByText("assistants")).toBeDefined();
  });

  it("sends an admin home from an instructor-only page", () => {
    // The gate is an allow-list, not a rank. An admin outranks an instructor
    // but supervises nobody - an assistant's supervisor must be an instructor -
    // so this page has no content for them and they administer from /users.
    as("root_admin");

    renderRoleGated(["instructor"]);

    expect(screen.getByTestId("home")).toBeDefined();
    expect(screen.queryByText("assistants")).toBeNull();
  });

  it("sends a teaching assistant home from the same page", () => {
    as("teaching_assistant");

    renderRoleGated(["instructor"]);

    expect(screen.getByTestId("home")).toBeDefined();
  });
});
