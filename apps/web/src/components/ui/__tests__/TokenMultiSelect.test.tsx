import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { installDomStubs } from "../../../test/dom-stubs";
import TokenMultiSelect, { type Choice } from "../TokenMultiSelect";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const CHOICES: Choice[] = [
  { value: "u1", label: "Alice Tan" },
  { value: "u2", label: "Bob Lim" },
  { value: "u3", label: "Chen Wei" },
];

function Harness({
  choices = CHOICES,
  initial = [] as string[],
  onChange,
}: {
  choices?: Choice[];
  initial?: string[];
  onChange?: (next: string[]) => void;
}) {
  const [selected, setSelected] = useState<string[]>(initial);
  return (
    <TokenMultiSelect
      choices={choices}
      selected={selected}
      onChange={(next) => {
        setSelected(next);
        onChange?.(next);
      }}
      placeholder="Add assistants"
    />
  );
}

/**
 * useRole("listbox") makes the trigger a combobox, the ARIA 1.2 pattern for a
 * control that opens a listbox — same as Dropdown's trigger.
 */
const trigger = () => screen.getByRole("combobox", { name: "Add assistants" });
const listbox = () => screen.getByRole("listbox", { name: "Add assistants" });
const option = (name: string) =>
  within(listbox()).getByRole("option", { name });

/** Same reasoning as Dropdown.test.tsx: Floating UI moves focus asynchronously. */
const expectFocused = (target: () => Element | null | undefined) =>
  waitFor(() => expect(document.activeElement).toBe(target()));
/** The popover fades out over 160ms, so closure is only true after it. */
const expectClosed = () =>
  waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());

beforeEach(() => installDomStubs());
afterEach(cleanup);

describe("TokenMultiSelect — closed state", () => {
  it("shows the placeholder when nothing is selected", () => {
    render(<Harness />);
    expect(trigger().textContent).toContain("Add assistants");
  });

  it("shows one token per selection instead of the placeholder", () => {
    render(<Harness initial={["u1", "u3"]} />);
    expect(trigger().textContent).not.toContain("Add assistants");
    expect(screen.getByText("Alice Tan")).toBeDefined();
    expect(screen.getByText("Chen Wei")).toBeDefined();
  });

  it("falls back to the raw value for a selection no longer in choices", () => {
    // A TA unlinked elsewhere still shows as a removable token, not a blank one.
    render(<Harness initial={["gone"]} />);
    expect(screen.getByRole("button", { name: "Remove gone" })).toBeDefined();
  });
});

describe("TokenMultiSelect — listbox", () => {
  it("opens a multi-select listbox reflecting the selection", async () => {
    render(<Harness initial={["u2"]} />);
    await userEvent.click(trigger());
    expect(listbox().getAttribute("aria-multiselectable")).toBe("true");
    expect(option("Bob Lim").getAttribute("aria-selected")).toBe("true");
    expect(option("Alice Tan").getAttribute("aria-selected")).toBe("false");
  });

  it("toggles on click and stays open for the next pick", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.click(trigger());
    await userEvent.click(option("Alice Tan"));
    await userEvent.click(option("Chen Wei"));
    await userEvent.click(option("Alice Tan"));
    expect(onChange.mock.calls).toEqual([[["u1"]], [["u1", "u3"]], [["u3"]]]);
    expect(listbox()).toBeDefined();
  });

  it("says so when there is nobody to pick", async () => {
    render(<Harness choices={[]} />);
    await userEvent.click(trigger());
    expect(screen.getByRole("status").textContent).toBe("Nobody available.");
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    render(<Harness />);
    await userEvent.click(trigger());
    await userEvent.keyboard("{Escape}");
    await expectClosed();
    await expectFocused(trigger);
  });

  it("stays open when a token inside the box is removed", async () => {
    // outsidePress ignores the box, so removing a token mid-pick does not
    // close the list the user is still choosing from.
    render(<Harness initial={["u1"]} />);
    await userEvent.click(trigger());
    await userEvent.click(
      screen.getByRole("button", { name: "Remove Alice Tan" }),
    );
    expect(listbox()).toBeDefined();
  });
});

describe("TokenMultiSelect — keyboard", () => {
  it("arrows to an option and toggles it with Enter or Space", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.tab();
    // Opening from the keyboard lands on the first option, ready to toggle.
    await userEvent.keyboard("{Enter}");
    await expectFocused(() => option("Alice Tan"));
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard("{ArrowDown}");
    await expectFocused(() => option("Bob Lim"));
    await userEvent.keyboard(" ");
    expect(onChange.mock.calls).toEqual([[["u1"]], [["u1", "u2"]]]);
  });

  it("jumps by typed label, and a typed space does not toggle", async () => {
    // "Chen Wei" contains a space; mid-typeahead it must extend the search,
    // not select whatever happens to be active.
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await expectFocused(() => option("Alice Tan"));
    await userEvent.keyboard("chen w");
    await expectFocused(() => option("Chen Wei"));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("TokenMultiSelect — removing tokens", () => {
  it("removes only that token", async () => {
    const onChange = vi.fn();
    render(<Harness initial={["u1", "u2"]} onChange={onChange} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Remove Alice Tan" }),
    );
    expect(onChange).toHaveBeenCalledWith(["u2"]);
    expect(screen.queryByText("Alice Tan")).toBeNull();
  });

  it("moves keyboard focus to the trigger so it is not lost with the token", async () => {
    render(<Harness initial={["u1"]} />);
    await userEvent.tab();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Remove Alice Tan" }),
    );
    await userEvent.keyboard("{Enter}");
    expect(document.activeElement).toBe(trigger());
  });
});
