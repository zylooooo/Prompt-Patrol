import Sidebar from "../Sidebar";
import type { User } from "../../api/auth";
import userEvent from "@testing-library/user-event";
import { installDomStubs } from "../../test/dom-stubs";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

/**
 * Drawer behaviour below `md`. Separate file because `useMediaQuery` caches its
 * MediaQueryList at module scope, so `matches: false` has to be the first stub
 * this module ever sees.
 */

const USER: User = { email: "ada@smu.edu.sg", role: "root_admin" };

beforeEach(() => installDomStubs({ matches: false }));
afterEach(cleanup);

const renderDrawer = (path = "/check") =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar user={USER} />
      <Routes>
        <Route path="*" element={<Link to="/history">go elsewhere</Link>} />
      </Routes>
    </MemoryRouter>,
  );

const opener = () => screen.getByRole("button", { name: "Open navigation" });
const closer = () => screen.getByRole("button", { name: "Close navigation" });
const aside = () => document.querySelector("aside")!;

describe("Sidebar drawer — closed state", () => {
  it("starts closed and inert, so Tab cannot reach it", () => {
    renderDrawer();
    expect(aside().hasAttribute("inert")).toBe(true);
  });

  it("reports collapsed on the opener", () => {
    renderDrawer();
    expect(opener().getAttribute("aria-expanded")).toBe("false");
  });

  it("points the opener at the region it controls", () => {
    renderDrawer();
    expect(
      document.getElementById(opener().getAttribute("aria-controls")!),
    ).toBe(aside());
  });

  it("renders no backdrop", () => {
    const { container } = renderDrawer();
    expect(
      container.querySelector('[aria-hidden="true"].fixed.inset-0'),
    ).toBeNull();
  });
});

describe("Sidebar drawer — opening", () => {
  it("opens, drops inert and reports expanded", async () => {
    renderDrawer();
    await userEvent.click(opener());
    expect(aside().hasAttribute("inert")).toBe(false);
    expect(opener().getAttribute("aria-expanded")).toBe("true");
  });

  it("moves focus into the drawer", async () => {
    // Opening a drawer and leaving focus behind strands a keyboard user.
    renderDrawer();
    await userEvent.click(opener());
    expect(document.activeElement).toBe(closer());
  });

  it("slides in rather than mounting", async () => {
    renderDrawer();
    expect(aside().className).toContain("-translate-x-full");
    await userEvent.click(opener());
    expect(aside().className).toContain("translate-x-0");
  });
});

describe("Sidebar drawer — dismissal", () => {
  it("closes on Escape and returns focus to the opener", async () => {
    renderDrawer();
    await userEvent.click(opener());
    await userEvent.keyboard("{Escape}");
    expect(aside().hasAttribute("inert")).toBe(true);
    expect(document.activeElement).toBe(opener());
  });

  it("closes on the close button and returns focus to the opener", async () => {
    renderDrawer();
    await userEvent.click(opener());
    await userEvent.click(closer());
    expect(aside().hasAttribute("inert")).toBe(true);
    expect(document.activeElement).toBe(opener());
  });

  it("closes when the backdrop is clicked, and restores focus", async () => {
    // Regression: focus restoration used to live in the individual close
    // handlers, so the backdrop and route-change paths stranded focus on a
    // node that had just gone inert.
    const { container } = renderDrawer();
    await userEvent.click(opener());
    const backdrop = container.querySelector(
      '[aria-hidden="true"].fixed.inset-0',
    );
    expect(backdrop).not.toBeNull();
    await userEvent.click(backdrop!);
    expect(aside().hasAttribute("inert")).toBe(true);
    expect(document.activeElement).toBe(opener());
  });

  it("never leaves focus inside the drawer after it goes inert", async () => {
    // Focus stuck on an inert node is unrecoverable by keyboard.
    renderDrawer();
    for (const dismiss of [
      async () => userEvent.keyboard("{Escape}"),
      async () => userEvent.click(closer()),
    ]) {
      await userEvent.click(opener());
      await dismiss();
      expect(aside().contains(document.activeElement)).toBe(false);
    }
  });

  it("closes when navigation completes", async () => {
    // Navigating is the point of the drawer; leaving it open covers the page
    // the user just asked for.
    renderDrawer();
    await userEvent.click(opener());
    await userEvent.click(
      within(screen.getByRole("navigation", { name: "Primary" })).getByRole(
        "link",
        { name: "History" },
      ),
    );
    expect(aside().hasAttribute("inert")).toBe(true);
  });

  it("closes on a navigation it did not originate", async () => {
    // Back/forward, or a link elsewhere on the page — closing is keyed on the
    // pathname, not on the click.
    renderDrawer();
    await userEvent.click(opener());
    await userEvent.click(screen.getByRole("link", { name: "go elsewhere" }));
    expect(aside().hasAttribute("inert")).toBe(true);
  });
});

describe("Sidebar drawer — focus containment", () => {
  it("pulls focus back when it escapes the open drawer", async () => {
    // Not a full trap: a focusin listener returns focus rather than a
    // hand-maintained tabbable list, which cannot drift out of step with the DOM.
    renderDrawer();
    await userEvent.click(opener());

    const outside = document.createElement("button");
    document.body.appendChild(outside);
    outside.focus();

    expect(document.activeElement).toBe(closer());
    outside.remove();
  });

  it("stops containing focus once closed", async () => {
    renderDrawer();
    await userEvent.click(opener());
    await userEvent.keyboard("{Escape}");

    const outside = document.createElement("button");
    document.body.appendChild(outside);
    outside.focus();

    expect(document.activeElement).toBe(outside);
    outside.remove();
  });
});
