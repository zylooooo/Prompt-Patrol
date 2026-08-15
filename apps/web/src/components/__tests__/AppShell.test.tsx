import AppShell from "../AppShell";
import { StrictMode } from "react";
import { renderRoute } from "../../test/render";
import { installDomStubs } from "../../test/dom-stubs";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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

describe("AppShell — focus management", () => {
  // The rest of this file pins classes; this one pins behaviour, because the
  // regression it guards was invisible to a DOM-order assertion.
  //
  // StrictMode must wrap the *router*, exactly as main.tsx does. Nesting it
  // inside the route element does not reproduce: React remounts that subtree and
  // the refs come back fresh, so the double-effect never sees stale state.
  const renderStrict = () =>
    render(
      <StrictMode>
        <QueryClientProvider
          client={
            new QueryClient({ defaultOptions: { queries: { retry: false } } })
          }
        >
          <MemoryRouter initialEntries={["/check"]}>
            <Routes>
              <Route path="/" element={<AppShell />}>
                <Route path="check" element={<p>page body</p>} />
              </Route>
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </StrictMode>,
    );

  it("does not pull focus into <main> on first render under StrictMode", () => {
    // React 19 double-invokes effects in dev, and a "have I run once?" ref flag
    // does not survive it: pass 1 clears the flag, pass 2 focuses <main>. Focus
    // starting inside <main> moves the browser's sequential-focus start point
    // past the skip link AND the whole sidebar, so the first Tab lands on page
    // content and the nav comes last — confirmed in Chromium, where the skip
    // link was reached 10th in dev and 1st in the production build. Comparing
    // pathnames instead is idempotent under a repeated effect.
    renderStrict();
    expect(document.activeElement).toBe(document.body);
  });

  it("still leaves <main> focusable for the skip link to target", () => {
    // Positive control: the fix must not work by making <main> unfocusable.
    renderStrict();
    const main = screen.getByRole("main");
    main.focus();
    expect(document.activeElement).toBe(main);
  });
});
