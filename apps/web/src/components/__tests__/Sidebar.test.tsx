import Sidebar from "../Sidebar";
import { NAV_ITEMS } from "../nav-items";
import type { User } from "../../api/auth";
import userEvent from "@testing-library/user-event";
import { installDomStubs } from "../../test/dom-stubs";
import { renderWithProviders } from "../../test/render";
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

/**
 * Desktop behaviour. `installDomStubs({ matches: true })` makes the
 * `(min-width: 48rem)` query match, and it must be the *first* stub this module
 * sees — `useMediaQuery` caches its MediaQueryList at module scope. Drawer
 * behaviour lives in Sidebar.mobile.test.tsx for the same reason.
 */

const asUser = (role: User["role"]): User => ({
  email: "ada@smu.edu.sg",
  role,
  provisionedBy: null,
});

beforeEach(() => installDomStubs({ matches: true }));
afterEach(cleanup);

const renderAt = (user: User | null, path = "/check") =>
  renderWithProviders(<Sidebar user={user} />, { route: path });

const navLinks = () =>
  within(screen.getByRole("navigation", { name: "Primary" })).queryAllByRole(
    "link",
  );

describe("Sidebar — role-gated navigation", () => {
  // Destinations are identified by href, not by label: role gating is about
  // which routes are reachable, and asserting the copy made every wording
  // change look like a permissions regression.
  const hrefs = () => navLinks().map((a) => a.getAttribute("href"));

  it("shows only the ungated destinations to a teaching assistant", () => {
    renderAt(asUser("teaching_assistant"));
    expect(hrefs()).toEqual(["/check", "/history"]);
  });

  it("adds teaching assistants for an instructor, but not users", () => {
    renderAt(asUser("instructor"));
    expect(hrefs()).toContain("/teaching-assistants");
    expect(hrefs()).not.toContain("/users");
  });

  it("labels every destination from NAV_ITEMS", () => {
    // The one place copy is asserted, so an empty or duplicated label is caught
    // without pinning the wording in five other tests.
    renderAt(asUser("root_admin"));
    const labels = navLinks().map((a) => a.textContent);
    expect(labels).toEqual(NAV_ITEMS.map((i) => i.label));
    expect(new Set(labels).size).toBe(labels.length);
    expect(labels.every((l) => (l ?? "").trim().length > 0)).toBe(true);
  });

  it("shows every destination to a root admin", () => {
    renderAt(asUser("root_admin"));
    expect(navLinks()).toHaveLength(NAV_ITEMS.length);
  });

  it("renders no destinations at all without a user", () => {
    // Falling back to the ungated subset would leak a nav for a session that
    // does not exist; the shell should not be rendering in this state anyway.
    renderAt(null);
    expect(navLinks()).toHaveLength(0);
  });

  it("keeps the declared order rather than the filtered order", () => {
    renderAt(asUser("root_admin"));
    expect(navLinks().map((a) => a.getAttribute("href"))).toEqual(
      NAV_ITEMS.map((i) => i.to),
    );
  });

  it("honours an injected item list", () => {
    renderWithProviders(
      <Sidebar
        user={asUser("teaching_assistant")}
        items={[{ to: "/x", label: "Injected" }]}
      />,
      { route: "/x" },
    );
    expect(navLinks().map((a) => a.textContent)).toEqual(["Injected"]);
  });
});

describe("Sidebar — active state", () => {
  it("marks exactly one link aria-current=page", () => {
    renderAt(asUser("root_admin"), "/history");
    const current = navLinks().filter(
      (a) => a.getAttribute("aria-current") === "page",
    );
    expect(current).toHaveLength(1);
    expect(current[0].getAttribute("href")).toBe("/history");
  });

  it("keeps the parent link current on a nested detail route", () => {
    // /history/:id must still light up the parent, or the user loses their place.
    renderAt(asUser("root_admin"), "/history/abc-123");
    const current = navLinks().filter(
      (a) => a.getAttribute("aria-current") === "page",
    );
    expect(current).toHaveLength(1);
    expect(current[0].getAttribute("href")).toBe("/history");
  });

  it("marks nothing current on a route outside the nav", () => {
    renderAt(asUser("root_admin"), "/somewhere-else");
    expect(
      navLinks().filter((a) => a.getAttribute("aria-current") === "page"),
    ).toHaveLength(0);
  });
});

describe("Sidebar — account block", () => {
  it("shows the signed-in email and role", () => {
    renderAt(asUser("root_admin"));
    expect(screen.getByText("ada@smu.edu.sg")).toBeDefined();
    expect(screen.getByText("Admin")).toBeDefined();
  });

  it("renders without an email or role when there is no user", () => {
    renderAt(null);
    expect(screen.getByRole("button", { name: "Sign out" })).toBeDefined();
  });

  it("wipes browser-local data on the way out, without blocking the POST", () => {
    // The submit handler is the only moment our JavaScript gets before the
    // browser leaves the page. It must clear, and must not preventDefault - a
    // cancelled submit means the session is never revoked server-side.
    localStorage.setItem("pp.history.v2", '["previous user history"]');
    localStorage.setItem("pp_login_hint", "ada@smu.edu.sg");

    renderAt(asUser("instructor"));
    const form = screen
      .getByRole("button", { name: "Sign out" })
      .closest("form")!;

    // jsdom does not implement form submission, so the native step is asserted
    // separately below; here we only need the handler to have run.
    const submitted = new SubmitEvent("submit", {
      bubbles: true,
      cancelable: true,
    });
    form.dispatchEvent(submitted);

    expect(localStorage.getItem("pp.history.v2")).toBeNull();
    expect(localStorage.getItem("pp_login_hint")).toBeNull();
    expect(submitted.defaultPrevented).toBe(false);
    localStorage.clear();
  });

  it("signs out through a real form POST, not a fetch", () => {
    // The endpoint answers 303 and the browser must follow it. If this ever
    // becomes an apiRequest, logout silently stops working.
    renderAt(asUser("instructor"));
    const submit = screen.getByRole("button", { name: "Sign out" });
    const form = submit.closest("form");
    expect(form?.getAttribute("method")).toBe("post");
    expect(form?.getAttribute("action")).toBe("/api/auth/logout");
    expect(submit.getAttribute("type")).toBe("submit");
  });
});

describe("Sidebar — desktop layout", () => {
  it("is not inert, so it is reachable by keyboard", () => {
    renderAt(asUser("root_admin"));
    expect(screen.getByRole("complementary").hasAttribute("inert")).toBe(false);
  });

  it("pins to the viewport instead of stretching with the page", () => {
    // The whole point of the extraction: `self-start` opts out of the flex
    // container's stretch and `h-dvh` fixes the height, so page length cannot
    // drag the sign-out block below the fold.
    const cls = renderAt(asUser("root_admin")).container.querySelector(
      "aside",
    )!.className;
    expect(cls).toContain("md:self-start");
    expect(cls).toContain("h-dvh");
    expect(cls).toContain("md:sticky");
  });

  it("scrolls the nav list, not the aside", () => {
    // Overflow has to live on the list so the brand and account block stay put.
    const { container } = renderAt(asUser("root_admin"));
    expect(container.querySelector("nav")!.className).toContain(
      "overflow-y-auto",
    );
    expect(container.querySelector("aside")!.className).not.toContain(
      "overflow-y-auto",
    );
  });

  it("hides the drawer controls", async () => {
    renderAt(asUser("root_admin"));
    // Present in the DOM but md:hidden — asserting they never take focus is
    // what actually matters on desktop.
    await userEvent.tab();
    expect(document.activeElement?.getAttribute("aria-label")).not.toBe(
      "Close navigation",
    );
  });
});
