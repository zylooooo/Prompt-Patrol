import { MemoryRouter, Route, Routes } from "react-router-dom";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GuestRoute } from "../GuestRoute";

/**
 * Every trip through the sign-in form mints another `sessions` row, and the
 * previous one cannot be revoked (see the note in 08-auth-and-security.md), so
 * the cheapest place to stop the pile-up is to not offer the form to someone
 * who is already signed in.
 */

const useAuthMock = vi.fn();
vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => useAuthMock() as unknown,
}));

const signedIn = {
  user: { email: "ada@smu.edu.sg", role: "instructor" },
  isPending: false,
  isError: false,
  error: null,
};
const signedOut = { user: null, isPending: false, isError: false, error: null };
const stillChecking = { ...signedOut, isPending: true };

function renderAt(route = "/login") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route
          path="/login"
          element={
            <GuestRoute>
              <p>sign-in form</p>
            </GuestRoute>
          }
        />
        <Route path="/" element={<p>the app</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("GuestRoute", () => {
  it("shows the form to a signed-out visitor", () => {
    useAuthMock.mockReturnValue(signedOut);

    renderAt();

    expect(screen.getByText("sign-in form")).toBeDefined();
  });

  it("sends a signed-in visitor to the app", () => {
    useAuthMock.mockReturnValue(signedIn);

    renderAt();

    expect(screen.getByText("the app")).toBeDefined();
    expect(screen.queryByText("sign-in form")).toBeNull();
  });

  it("shows the form while the session is still resolving", () => {
    // The common visitor is signed out. Withholding the form from everyone to
    // spare the rare signed-in one a flash would be the wrong trade.
    useAuthMock.mockReturnValue(stillChecking);

    renderAt();

    expect(screen.getByText("sign-in form")).toBeDefined();
  });

  it("still shows a failure message to a signed-in visitor", () => {
    // Signing in as a second, unprovisioned account lands here while the first
    // session is still valid. Redirecting would swallow the only explanation.
    useAuthMock.mockReturnValue(signedIn);

    renderAt("/login?error=not_provisioned");

    expect(screen.getByText("sign-in form")).toBeDefined();
    expect(screen.queryByText("the app")).toBeNull();
  });

  it("redirects a signed-in visitor when the query string carries no reason", () => {
    useAuthMock.mockReturnValue(signedIn);

    renderAt("/login?next=%2Fhistory");

    expect(screen.getByText("the app")).toBeDefined();
  });
});
