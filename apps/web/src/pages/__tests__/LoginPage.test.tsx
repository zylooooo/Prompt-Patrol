import { MemoryRouter } from "react-router-dom";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import LoginPage from "../LoginPage";

/**
 * Every redirect the API or ProtectedRoute can send here carries an `error`
 * code. An unmapped code must still say something, or the user lands on a login
 * page with no explanation for why they are looking at it.
 */

const renderAt = (search = "") =>
  render(
    <MemoryRouter initialEntries={[`/login${search}`]}>
      <LoginPage />
    </MemoryRouter>,
  );

const alertText = () => screen.queryByRole("alert")?.textContent ?? null;

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
});

describe("LoginPage — redirect reasons", () => {
  it("shows no alert when arriving without a reason", () => {
    renderAt();
    expect(alertText()).toBeNull();
  });

  it.each([
    ["?error=session_expired", "90 minutes without activity"],
    ["?error=session_ended", "maximum of 12 hours"],
    ["?error=session_revoked", "ended, either by signing out"],
    ["?error=session_unknown", "couldn't recognise your session"],
    ["?error=account_deactivated", "turned off while you were signed in"],
    ["?error=signed_out", "You're signed out"],
    ["?error=not_provisioned", "isn't set up"],
    ["?error=sign_in_cancelled", "cancelled"],
    ["?error=sign_in_failed", "couldn't complete sign-in"],
    ["?error=deactivated", "turned off"],
    ["?error=deleted", "has been removed"],
  ])("explains %s", (search, expected) => {
    renderAt(search);
    expect(alertText()).toContain(expected);
  });

  it("admits it has no specific reason rather than inventing one", () => {
    renderAt("?error=something_new");
    expect(alertText()).toContain("don't have a more specific reason");
  });

  it("prefills the email field from the stored hint", () => {
    localStorage.setItem("pp_login_hint", "ada@smu.edu.sg");

    renderAt();

    expect(screen.getByLabelText<HTMLInputElement>("Email").value).toBe(
      "ada@smu.edu.sg",
    );
  });
});

describe("LoginPage — after a deliberate sign-out", () => {
  it("acknowledges the sign-out rather than saying nothing", () => {
    // The trip out goes through Auth0 and lands back on a bare URL, so without
    // the marker the person who just pressed Sign out arrives at a blank login
    // page with no confirmation that it worked.
    sessionStorage.setItem("pp_signed_out", "1");

    renderAt();

    expect(screen.getByRole("status").textContent).toContain(
      "You've been signed out",
    );
    expect(alertText()).toBeNull();
  });

  it("is a status, not an alarm, and shows only once", () => {
    sessionStorage.setItem("pp_signed_out", "1");

    const first = renderAt();
    expect(screen.getByRole("status")).toBeDefined();
    first.unmount();

    renderAt();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("lets a real failure win over the sign-out acknowledgement", () => {
    // Arriving with both means the sign-out completed and the next sign-in
    // failed. The failure is the part that needs explaining.
    sessionStorage.setItem("pp_signed_out", "1");

    renderAt("?error=not_provisioned");

    expect(alertText()).toContain("isn't set up");
    expect(screen.queryByRole("status")).toBeNull();
  });
});
