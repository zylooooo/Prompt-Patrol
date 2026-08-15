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
import Dropdown, { type DropdownOption } from "../Dropdown";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * ARIA relationships are ids pointing at other ids, and a typo in one of them
 * fails silently — the markup still renders, the tests still pass, and only a
 * screen reader notices. These assertions resolve each reference against the
 * document rather than string-matching an attribute.
 *
 * This matters most for the searchable mode, which has no call site in the app
 * yet, so this file is the only thing standing behind it.
 */

const OPTIONS: DropdownOption<string>[] = [
  { value: "alpha", label: "Alpha" },
  { value: "bravo", label: "Bravo" },
];

function Harness(props: Partial<Parameters<typeof Dropdown<string>>[0]> = {}) {
  const [value, setValue] = useState<string | null>(null);
  return (
    <Dropdown<string>
      value={value}
      onChange={setValue}
      options={OPTIONS}
      placeholder="Pick one"
      ariaLabel="Picker"
      {...props}
    />
  );
}

/** Resolve an IDREF attribute to the element it names, or null. */
const target = (el: Element, attr: string) => {
  const id = el.getAttribute(attr);
  return id ? document.getElementById(id) : null;
};

beforeEach(() => installDomStubs());
afterEach(cleanup);

describe("Dropdown — plain mode is a select-only combobox", () => {
  it("points aria-controls at the listbox itself, not at a wrapper", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("combobox", { name: "Picker" });
    await userEvent.click(trigger);

    const controlled = target(trigger, "aria-controls");
    expect(controlled).not.toBeNull();
    expect(controlled).toBe(screen.getByRole("listbox", { name: "Picker" }));
  });

  it("advertises the popup kind that actually opens", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("combobox", { name: "Picker" });
    expect(trigger.getAttribute("aria-haspopup")).toBe("listbox");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    await userEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
  });

  it("puts nothing but options and groups inside the listbox", async () => {
    render(
      <Harness
        groups={[
          { label: "First", options: [{ value: "a", label: "Apple" }] },
          { label: "Second", options: [{ value: "b", label: "Banana" }] },
        ]}
        options={[]}
        footer={<span>Footer text</span>}
      />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Picker" }));
    const listbox = screen.getByRole("listbox", { name: "Picker" });

    // Walk the accessibility-relevant children: everything exposed under a
    // listbox must be an option or a group.
    const exposed = Array.from(
      listbox.querySelectorAll("[role]:not([role='presentation'])"),
    ).map((el) => el.getAttribute("role"));
    expect(new Set(exposed)).toEqual(new Set(["group", "option"]));

    // The footer is chrome, so it belongs outside the list.
    expect(within(listbox).queryByText("Footer text")).toBeNull();
    expect(screen.getByText("Footer text")).toBeDefined();
  });

  it("names each group so its options are announced under it", async () => {
    render(
      <Harness
        options={[]}
        groups={[{ label: "First", options: [{ value: "a", label: "Apple" }] }]}
      />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Picker" }));
    const group = screen.getByRole("group", { name: "First" });
    expect(within(group).getByRole("option", { name: /Apple/ })).toBeDefined();
  });

  it("renders grouped options without React complaining about keys", async () => {
    // The grouped branch returns bare arrays from a map, which is the classic
    // way to lose keys silently. React only warns, so nothing else would catch it.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <Harness
        options={[]}
        groups={[
          { label: "First", options: [{ value: "a", label: "Apple" }] },
          { label: "Second", options: [{ value: "b", label: "Banana" }] },
        ]}
        resetLabel="Any"
      />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Picker" }));
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("marks disabled options with aria-disabled rather than dropping them", async () => {
    render(
      <Harness
        options={[
          { value: "a", label: "Apple" },
          { value: "b", label: "Banana", disabled: true },
        ]}
      />,
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Picker" }));
    const banana = screen.getByRole("option", { name: /Banana/ });
    expect(banana.getAttribute("aria-disabled")).toBe("true");
  });
});

describe("Dropdown — searchable mode is a combobox inside a dialog", () => {
  const open = async () => {
    const trigger = screen.getByRole("button", { name: "Picker" });
    await userEvent.click(trigger);
    await waitFor(() =>
      expect((document.activeElement as HTMLElement).tagName).toBe("INPUT"),
    );
    return trigger;
  };

  it("opens a dialog, and says so on the trigger", async () => {
    render(<Harness searchPlaceholder="Search…" />);
    const trigger = await open();
    expect(trigger.getAttribute("aria-haspopup")).toBe("dialog");
    // Named, or a screen reader announces only "dialog".
    const dialog = screen.getByRole("dialog", { name: "Picker" });
    expect(target(trigger, "aria-controls")).toBe(dialog);
  });

  it("makes the filter field the combobox, pointed at the listbox", async () => {
    render(<Harness searchPlaceholder="Search…" />);
    await open();
    const input = screen.getByRole("combobox");
    expect(input.tagName).toBe("INPUT");
    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(input.getAttribute("aria-autocomplete")).toBe("list");
    expect(target(input, "aria-controls")).toBe(screen.getByRole("listbox"));
  });

  it("tracks the highlighted option with aria-activedescendant", async () => {
    render(<Harness searchPlaceholder="Search…" />);
    await open();
    const input = screen.getByRole("combobox");

    // Nothing highlighted yet, so nothing to point at.
    expect(input.getAttribute("aria-activedescendant")).toBeNull();

    await userEvent.keyboard("{ArrowDown}");
    await waitFor(() =>
      expect(input.getAttribute("aria-activedescendant")).not.toBeNull(),
    );

    // The reference must resolve, and resolve to the option that is active.
    const active = target(input, "aria-activedescendant");
    expect(active).not.toBeNull();
    expect(active?.getAttribute("role")).toBe("option");
    expect(active?.textContent).toContain("Alpha");
  });

  it("keeps focus in the field so the activedescendant is meaningful", async () => {
    // aria-activedescendant is only honoured on the focused element. If arrowing
    // moved real focus onto a row, the attribute would describe nothing.
    render(<Harness searchPlaceholder="Search…" />);
    await open();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    expect((document.activeElement as HTMLElement).tagName).toBe("INPUT");
    for (const option of screen.getAllByRole("option")) {
      expect(option.getAttribute("tabindex")).toBeNull();
    }
  });
});
