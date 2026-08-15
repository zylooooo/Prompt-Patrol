import Page, { PageFill, PageScroll } from "../Page";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

/**
 * jsdom performs no layout, so these assert the *contract* — which classes
 * carry the height model — rather than measured pixels. That is the useful
 * thing to pin: the failure mode in a browser is always a missing `min-h-0` or
 * a stray `overflow`, and both are visible in the class list.
 */

const classesOf = (el: Element | null) => el?.className ?? "";

afterEach(cleanup);

describe("Page", () => {
  it("fills its parent exactly and lays out as a column", () => {
    const { container } = render(<Page>content</Page>);
    const cls = classesOf(container.firstElementChild);
    expect(cls).toContain("h-full");
    expect(cls).toContain("flex-col");
  });

  it("can shrink below its content", () => {
    // Without min-h-0 a flex item refuses to shrink past its content, the
    // column grows past the viewport, and the scrollbar reappears on <body> —
    // the exact bug this layout exists to prevent.
    const { container } = render(<Page>content</Page>);
    expect(classesOf(container.firstElementChild)).toContain("min-h-0");
  });

  it("does not scroll — a page delegates that to one inner region", () => {
    const { container } = render(<Page>content</Page>);
    expect(classesOf(container.firstElementChild)).not.toContain("overflow-y");
  });
});

describe("PageScroll", () => {
  it("absorbs the overflow and can shrink", () => {
    const { container } = render(<PageScroll>content</PageScroll>);
    const cls = classesOf(container.firstElementChild);
    expect(cls).toContain("overflow-y-auto");
    expect(cls).toContain("min-h-0");
    expect(cls).toContain("flex-1");
  });

  it("keeps a caller's className instead of replacing it", () => {
    const { container } = render(
      <PageScroll className="mt-6">content</PageScroll>,
    );
    const cls = classesOf(container.firstElementChild);
    expect(cls).toContain("mt-6");
    expect(cls).toContain("overflow-y-auto");
  });

  it("forwards arbitrary props, so it can carry a role", () => {
    // CheckPage makes its scroll region the tabpanel rather than nesting an
    // extra div inside it.
    render(
      <PageScroll role="tabpanel" id="panel-x" aria-label="Panel">
        content
      </PageScroll>,
    );
    expect(screen.getByRole("tabpanel", { name: "Panel" }).id).toBe("panel-x");
  });
});

describe("PageFill", () => {
  it("hands its height to a filling child and can shrink", () => {
    const { container } = render(<PageFill>content</PageFill>);
    const cls = classesOf(container.firstElementChild);
    expect(cls).toContain("min-h-0");
    expect(cls).toContain("flex-1");
    expect(cls).toContain("flex-col");
  });

  it("does not scroll — the table body inside it does", () => {
    // Two nested scrollers would fight, and the table's sticky header and
    // pinned footer only work when the table owns the scroll.
    const { container } = render(<PageFill>content</PageFill>);
    expect(classesOf(container.firstElementChild)).not.toContain("overflow-y");
  });

  it("keeps a caller's className", () => {
    const { container } = render(<PageFill className="mt-5">x</PageFill>);
    expect(classesOf(container.firstElementChild)).toContain("mt-5");
  });
});
