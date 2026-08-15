import AppShell from "../AppShell";
import { Route } from "react-router-dom";
import { renderRoute } from "../../test/render";
import { cleanup, screen } from "@testing-library/react";
import { installDomStubs } from "../../test/dom-stubs";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

/**
 * The shell's job is to be exactly one viewport tall and never scroll. jsdom
 * does no layout, so these pin the classes that encode that — which is where
 * the regression actually happens.
 */

const renderShell = () =>
  renderRoute(<AppShell />, {
    route: "/check",
    children: <Route path="/check" element={<p>page body</p>} />,
  });

beforeEach(() => installDomStubs({ matches: true }));
afterEach(cleanup);

describe("AppShell — height model", () => {
  it("is exactly one viewport tall", () => {
    const { container } = renderShell();
    // h-dvh, not h-screen: mobile browser chrome overflows 100vh.
    expect(container.firstElementChild?.className).toContain("h-dvh");
  });

  it("never grows with its content", () => {
    const { container } = renderShell();
    const cls = container.firstElementChild?.className ?? "";
    expect(cls).not.toContain("min-h-dvh");
    expect(cls).not.toContain("min-h-screen");
  });

  it("hides its own overflow, so there is no window scrollbar", () => {
    const { container } = renderShell();
    expect(container.firstElementChild?.className).toContain("overflow-hidden");
  });
});

describe("AppShell — content area", () => {
  const main = () => screen.getByRole("main");

  it("is a shrinkable flex column, not a scroll container", () => {
    // Pages nominate their own scrolling region so a table can keep its header
    // sticky; if <main> scrolled instead, that would be impossible.
    renderShell();
    const cls = main().className;
    expect(cls).toContain("min-h-0");
    expect(cls).toContain("flex-col");
    expect(cls).not.toContain("overflow-y-auto");
  });

  it("can shrink horizontally, so a wide table cannot widen the shell", () => {
    renderShell();
    expect(main().className).toContain("min-w-0");
  });

  it("renders the routed page", () => {
    renderShell();
    expect(screen.getByText("page body")).toBeDefined();
  });

  it("is focusable but not in the tab order", () => {
    // Focused programmatically on navigation; tabIndex -1 keeps it out of the
    // sequential order so Tab does not stop on the page container.
    renderShell();
    expect(main().getAttribute("tabindex")).toBe("-1");
  });
});

describe("AppShell — skip link", () => {
  it("is the first thing Tab reaches and targets main", () => {
    const { container } = renderShell();
    const skip = container.querySelector("a[href='#main-content']");
    expect(skip).not.toBeNull();
    expect(container.firstElementChild?.firstElementChild).toBe(skip);
    expect(screen.getByRole("main").id).toBe("main-content");
  });
});
