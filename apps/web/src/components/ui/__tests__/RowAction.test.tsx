import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import RowAction, { RowActionLink } from "../RowAction";

const classesOf = (el: Element) => el.className.split(/\s+/);

function renderBoth() {
  render(
    <MemoryRouter>
      <RowAction onClick={() => {}}>Edit</RowAction>
      <RowActionLink to="/history/1">View</RowActionLink>
    </MemoryRouter>,
  );
  return {
    button: screen.getByRole("button", { name: "Edit" }),
    link: screen.getByRole("link", { name: "View" }),
  };
}

afterEach(cleanup);

describe("RowAction — rest state", () => {
  it("is a primary text link on a transparent ground", () => {
    const { button } = renderBoth();
    const cls = classesOf(button);
    expect(cls).toContain("text-primary");
    expect(cls).toContain("rounded-md");
    expect(cls).toContain("px-2.5");
    expect(cls).toContain("py-[5px]");
    // Any unprefixed bg-* would paint a resting fill.
    expect(cls.filter((c) => c.startsWith("bg-"))).toEqual([]);
  });

  it("puts the pointer cursor on the padded box, not just the glyphs", () => {
    // inline-flex makes the padding part of the box for the <a> variant too;
    // a bare inline <a> only grows its background, not its layout.
    const { button, link } = renderBoth();
    for (const el of [button, link]) {
      expect(classesOf(el)).toContain("cursor-pointer");
      expect(classesOf(el)).toContain("inline-flex");
    }
  });

  it("renders the button and the link identically", () => {
    // The point of the component: two tables cannot drift apart.
    const { button, link } = renderBoth();
    expect(link.className).toBe(button.className);
  });
});

describe("RowAction — hover and focus", () => {
  it("fills on hover without touching padding, font or colour", () => {
    // A hover-only change in px/py/text-* would shift the neighbouring action.
    const { button } = renderBoth();
    const hover = classesOf(button).filter((c) => c.startsWith("hover:"));
    expect(hover).toEqual(["hover:bg-primary-soft"]);
  });

  it("shows focus as the hover fill, never a ring", () => {
    // Rings are banned app-wide — see src/__tests__/focus-indicators.test.ts.
    const cls = classesOf(renderBoth().button);
    expect(cls).toContain("focus-visible:bg-primary-soft");
    expect(
      cls.filter((c) => /^focus(-visible)?:(ring|outline)-/.test(c)),
    ).toEqual([]);
  });

  it("is reachable in tab order", async () => {
    const { button, link } = renderBoth();
    await userEvent.tab();
    expect(document.activeElement).toBe(button);
    await userEvent.tab();
    expect(document.activeElement).toBe(link);
  });

  it("defaults to type=button so it cannot submit a surrounding form", () => {
    expect(renderBoth().button.getAttribute("type")).toBe("button");
  });
});

describe("RowAction — disabled", () => {
  it("dims and drops pointer events", () => {
    const cls = classesOf(renderBoth().button);
    expect(cls).toContain("disabled:opacity-45");
    expect(cls).toContain("disabled:pointer-events-none");
  });

  it("does not fire when disabled", async () => {
    const onClick = vi.fn();
    render(
      <RowAction onClick={onClick} disabled>
        Edit
      </RowAction>,
    );
    await userEvent.click(screen.getByRole("button"), {
      pointerEventsCheck: 0,
    });
    expect(onClick).not.toHaveBeenCalled();
  });

  it("is skipped in tab order", async () => {
    render(
      <>
        <RowAction onClick={() => {}} disabled>
          Edit
        </RowAction>
        <RowAction onClick={() => {}}>Delete</RowAction>
      </>,
    );
    await userEvent.tab();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Delete" }),
    );
  });
});

describe("RowAction — behaviour", () => {
  it("fires onClick from the mouse and the keyboard", async () => {
    const onClick = vi.fn();
    render(<RowAction onClick={onClick}>Edit</RowAction>);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await userEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(2);
  });

  it("navigates as a real link, not a click handler", () => {
    expect(renderBoth().link.getAttribute("href")).toBe("/history/1");
  });
});
