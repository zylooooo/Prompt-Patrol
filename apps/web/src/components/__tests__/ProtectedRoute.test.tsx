import type { ReactNode } from "react";
import { LOGIN_HINT_KEY } from "../../api/auth";
import { ProtectedRoute } from "../ProtectedRoute";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

/**
 * An idle session dies server-side (90 minutes) with nothing telling the
 * browser. The user finds out when a refetch bounces them here, so the bounce
 * has to explain itself rather than looking like a random logout.
 */

const useAuthMock = vi.fn();
vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => useAuthMock() as unknown,
}));

const resolved = (user: unknown) => ({
  user,
  isPending: false,
  isError: false,
  error: null,
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
});

describe("ProtectedRoute", () => {
  it("renders the route when a session resolves", () => {
    useAuthMock.mockReturnValue(
      resolved({ email: "ada@smu.edu.sg", role: "instructor" }),
    );

    renderGuarded();

    expect(screen.getByText("protected content")).toBeDefined();
  });

  it("renders nothing while the session is still resolving", () => {
    useAuthMock.mockReturnValue({
      user: null,
      isPending: true,
      isError: false,
      error: null,
    });

    const { container } = renderGuarded();

    // Deliberate: a flash of the login page before the session resolves is
    // worse than a blank frame.
    expect(container.textContent).toBe("");
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

  it("does not call a server error an expired session", () => {
    // Otherwise a backend outage tells every user their session timed out and
    // sends them round the sign-in loop for nothing.
    localStorage.setItem(LOGIN_HINT_KEY, "ada@smu.edu.sg");
    useAuthMock.mockReturnValue({
      user: null,
      isPending: false,
      isError: true,
      error: new Error("boom"),
    });

    renderGuarded();

    expect(screen.getByTestId("login").textContent).toBe("login:no-reason");
  });
});
