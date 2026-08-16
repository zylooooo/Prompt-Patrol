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

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("LoginPage — redirect reasons", () => {
  it("shows no alert when arriving without a reason", () => {
    renderAt();
    expect(alertText()).toBeNull();
  });

  it.each([
    ["?error=session_expired", "timed out"],
    ["?error=not_provisioned", "isn't set up"],
    ["?error=sign_in_cancelled", "cancelled"],
    ["?error=sign_in_failed", "couldn't complete sign-in"],
    ["?error=deactivated", "turned off"],
    ["?error=deleted", "has been removed"],
  ])("explains %s", (search, expected) => {
    renderAt(search);
    expect(alertText()).toContain(expected);
  });

  it("falls back to a generic message for an unknown code", () => {
    renderAt("?error=something_new");
    expect(alertText()).toContain("Sign-in failed");
  });

  it("prefills the email field from the stored hint", () => {
    localStorage.setItem("pp_login_hint", "ada@smu.edu.sg");

    renderAt();

    expect(screen.getByLabelText<HTMLInputElement>("Email").value).toBe(
      "ada@smu.edu.sg",
    );
  });
});
