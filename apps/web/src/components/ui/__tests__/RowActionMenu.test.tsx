import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { installDomStubs } from "../../../test/dom-stubs";
import RowActionMenu, { type RowActionMenuItem } from "../RowActionMenu";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function makeItems(overrides: Partial<RowActionMenuItem>[] = []) {
  const base: RowActionMenuItem[] = [
    { label: "Change role", onClick: vi.fn() },
    { label: "Resend invite", onClick: vi.fn() },
    { label: "Delete user", onClick: vi.fn(), destructive: true },
  ];
  return base.map((item, i) => ({ ...item, ...overrides[i] }));
}

const trigger = () => screen.getByRole("button", { name: "More actions" });
const menu = () => screen.getByRole("menu");
const items = () => within(menu()).getAllByRole("menuitem");
const item = (name: string) => screen.getByRole("menuitem", { name });

/** Same reasoning as Dropdown.test.tsx: Floating UI moves focus asynchronously. */
const expectFocused = (target: () => Element | null | undefined) =>
  waitFor(() => expect(document.activeElement).toBe(target()));
const expectClosed = () =>
  waitFor(() => expect(screen.queryByRole("menu")).toBeNull());

beforeEach(() => installDomStubs());
afterEach(cleanup);

describe("RowActionMenu — trigger", () => {
  it("is an icon button named by its aria-label", () => {
    render(<RowActionMenu items={makeItems()} ariaLabel="More actions" />);
    expect(trigger().getAttribute("type")).toBe("button");
    expect(trigger().getAttribute("aria-haspopup")).toBe("menu");
  });

  it("renders nothing when the row has no extra actions", () => {
    // An empty ⋯ that opens onto nothing is a dead control.
    const { container } = render(
      <RowActionMenu items={[]} ariaLabel="More actions" />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("does not open when disabled", async () => {
    render(
      <RowActionMenu items={makeItems()} ariaLabel="More actions" disabled />,
    );
    await userEvent.click(trigger(), { pointerEventsCheck: 0 });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("matches RowAction's focus and disabled treatment", () => {
    render(<RowActionMenu items={makeItems()} ariaLabel="More actions" />);
    const cls = trigger().className.split(/\s+/);
    expect(cls).toContain("focus-visible:bg-primary-soft");
    expect(cls).toContain("disabled:opacity-45");
    expect(cls).toContain("disabled:pointer-events-none");
  });
});

describe("RowActionMenu — opening and closing", () => {
  it("opens on click and reports it", async () => {
    render(<RowActionMenu items={makeItems()} ariaLabel="More actions" />);
    await userEvent.click(trigger());
    expect(items().map((el) => el.textContent)).toEqual([
      "Change role",
      "Resend invite",
      "Delete user",
    ]);
    expect(trigger().getAttribute("aria-expanded")).toBe("true");
  });

  it("closes on Escape and hands focus back to the trigger", async () => {
    render(<RowActionMenu items={makeItems()} ariaLabel="More actions" />);
    await userEvent.click(trigger());
    await userEvent.keyboard("{Escape}");
    await expectClosed();
    await expectFocused(trigger);
  });

  it("closes on an outside click", async () => {
    render(
      <>
        <RowActionMenu items={makeItems()} ariaLabel="More actions" />
        <p>outside</p>
      </>,
    );
    await userEvent.click(trigger());
    await userEvent.click(screen.getByText("outside"));
    await expectClosed();
  });
});

describe("RowActionMenu — keyboard", () => {
  it("opens from the keyboard and arrows through the items, looping", async () => {
    render(<RowActionMenu items={makeItems()} ariaLabel="More actions" />);
    await userEvent.tab();
    // Opening from the keyboard lands on the first item.
    await userEvent.keyboard("{Enter}");
    await expectFocused(() => item("Change role"));
    await userEvent.keyboard("{ArrowUp}");
    await expectFocused(() => item("Delete user"));
  });

  it("skips disabled items while arrowing", async () => {
    render(
      <RowActionMenu
        items={makeItems([{}, { disabled: true }])}
        ariaLabel="More actions"
      />,
    );
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await expectFocused(() => item("Change role"));
    await userEvent.keyboard("{ArrowDown}");
    await expectFocused(() => item("Delete user"));
  });

  it("jumps to an item by typing its first letters", async () => {
    render(<RowActionMenu items={makeItems()} ariaLabel="More actions" />);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await expectFocused(() => item("Change role"));
    await userEvent.keyboard("de");
    await expectFocused(() => item("Delete user"));
  });
});

describe("RowActionMenu — activation", () => {
  it("closes first, then runs the action", async () => {
    // The action runs on a timeout so a dialog it opens keeps focus instead of
    // losing it to the trigger when the menu unmounts.
    const list = makeItems();
    render(<RowActionMenu items={list} ariaLabel="More actions" />);
    await userEvent.click(trigger());
    await userEvent.click(item("Resend invite"));
    await expectClosed();
    await waitFor(() => expect(list[1].onClick).toHaveBeenCalledTimes(1));
    expect(list[0].onClick).not.toHaveBeenCalled();
  });

  it("does nothing when a disabled item is clicked", async () => {
    const list = makeItems([{ disabled: true }]);
    render(<RowActionMenu items={list} ariaLabel="More actions" />);
    await userEvent.click(trigger());
    await userEvent.click(item("Change role"), { pointerEventsCheck: 0 });
    // Give the deferred onClick its chance to (wrongly) fire.
    await new Promise((r) => setTimeout(r, 10));
    expect(list[0].onClick).not.toHaveBeenCalled();
    expect(screen.getByRole("menu")).toBeDefined();
  });

  it("marks destructive items in the danger colour only", async () => {
    render(<RowActionMenu items={makeItems()} ariaLabel="More actions" />);
    await userEvent.click(trigger());
    expect(item("Delete user").className).toContain("text-danger");
    expect(item("Change role").className).not.toContain("text-danger");
  });
});
