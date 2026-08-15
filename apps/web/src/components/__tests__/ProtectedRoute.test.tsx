import type { ReactNode } from "react";
import { LOGIN_HINT_KEY } from "../../api/auth";
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
  isPending: true,
  isError: false,
  error: null,
  refetch,
};

const resolved = (user: unknown) => ({
  user,
  isPending: false,
  isError: false,
  error: null,
  refetch,
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

// Stands in for LoginPage so the assertion is on the reason carried in the URL.
// Reads the router's location, not window.location - MemoryRouter never touches
// the latter, so window.location.search is always empty here.
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
  // In afterEach, not at the end of each test body: a test that fails before
  // its last line would otherwise leave fake timers installed and take
  // unrelated tests down with it.
  vi.useRealTimers();
});

describe("ProtectedRoute", () => {
  it("renders the route when a session resolves", () => {
    useAuthMock.mockReturnValue(
      resolved({ email: "ada@smu.edu.sg", role: "instructor" }),
    );

    renderGuarded();

    expect(screen.getByText("protected content")).toBeDefined();
  });

  it("renders nothing for a session check that answers promptly", () => {
    // A flash of the login page would state an answer the app does not have
    // yet; a spinner for 30ms is just a flicker. Neither, briefly, is correct.
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

  it("blames an expired session when this browser held one", () => {
    localStorage.setItem(LOGIN_HINT_KEY, "ada@smu.edu.sg");
    useAuthMock.mockReturnValue(resolved(null));

    renderGuarded();

    expect(screen.getByTestId("login").textContent).toBe(
      "login:session_expired",
    );
  });

  it("blames nothing on a first visit", () => {
    useAuthMock.mockReturnValue(resolved(null));

    renderGuarded();

    expect(screen.getByTestId("login").textContent).toBe("login:no-reason");
  });

  it("says the server is unreachable instead of claiming a sign-out", async () => {
    // The whole point: a failed session check is not an answer about who the
    // user is. Sending them to /login states, wrongly, that they are signed
    // out - and the sign-in they would then attempt runs through the same dead
    // backend, so an outage reads as a broken account.
    localStorage.setItem(LOGIN_HINT_KEY, "ada@smu.edu.sg");
    useAuthMock.mockReturnValue({
      user: null,
      isPending: false,
      isError: true,
      error: new Error("boom"),
      refetch,
    });

    renderGuarded();

    expect(screen.queryByTestId("login")).toBeNull();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("Can't reach Prompt Patrol");
    expect(alert.textContent).toContain("have not been signed out");

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
