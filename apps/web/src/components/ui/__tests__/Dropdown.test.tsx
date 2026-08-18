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

const OPTIONS: DropdownOption<string>[] = [
  { value: "alpha", label: "Alpha" },
  { value: "bravo", label: "Bravo" },
  { value: "charlie", label: "Charlie" },
];

function Harness({
  options = OPTIONS,
  initial = null as string | null,
  onChange,
  ...rest
}: {
  options?: DropdownOption<string>[];
  initial?: string | null;
  onChange?: (next: string | null) => void;
} & Partial<Parameters<typeof Dropdown<string>>[0]>) {
  const [value, setValue] = useState<string | null>(initial);
  return (
    <Dropdown<string>
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
      options={options}
      placeholder="Pick one"
      ariaLabel="Picker"
      {...rest}
    />
  );
}

/**
 * The trigger is a `<button>` element with `role="combobox"`, not a button role.
 * That is the ARIA 1.2 select-only combobox pattern: a control that opens a
 * listbox and holds a value is a combobox, and screen readers announce it as
 * "combo box, collapsed" rather than as a plain button.
 */
const trigger = () => screen.getByRole("combobox", { name: "Picker" });
/**
 * A searchable menu is a dialog that contains its own combobox (the filter
 * field), so its trigger is an ordinary button advertising `haspopup="dialog"`.
 * Putting `role="combobox"` on a control whose text field lives elsewhere would
 * claim a relationship the markup cannot honour.
 */
const searchTrigger = () => screen.getByRole("button", { name: "Picker" });
const listbox = () => screen.getByRole("listbox", { name: "Picker" });
const options = () => within(listbox()).getAllByRole("option");

/**
 * The popover exits through `AnimatePresence` over 160ms, so it is still in the
 * tree the moment `isOpen` flips. Asserting closure synchronously would be
 * asserting against the exit animation, not against the component.
 */
const expectClosed = () =>
  waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());

/**
 * List navigation moves DOM focus asynchronously — Floating UI defers it so it
 * does not fight the browser's own focus handling mid-keystroke. Asserting
 * synchronously would race that, exactly as `expectClosed` would race the exit.
 *
 * Always assert focus through this, by element identity. Never write
 * `expect(document.activeElement?.textContent).toContain("Apple")`: the trigger
 * renders an invisible width-measuring span for *every* option label
 * (`Dropdown.tsx`, `candidateLabels`), so its own textContent is
 * "Pick oneLoading…AppleBananaPick one" — measured, not guessed. A `toContain`
 * check is therefore satisfied by the trigger itself, so `waitFor` can succeed
 * on a poll taken before focus has left the trigger at all.
 *
 * `options()` can only ever return elements inside the listbox, so an identity
 * assertion cannot resolve early no matter how the scheduler behaves.
 */
const expectFocused = (target: () => Element | null | undefined) =>
  waitFor(() => expect(document.activeElement).toBe(target()));

beforeEach(() => installDomStubs());
afterEach(cleanup);

describe("Dropdown — trigger semantics", () => {
  it("advertises a listbox and tracks its expanded state", async () => {
    render(<Harness />);
    expect(trigger().getAttribute("aria-haspopup")).toBe("listbox");
    expect(trigger().getAttribute("aria-expanded")).toBe("false");
    await userEvent.click(trigger());
    expect(trigger().getAttribute("aria-expanded")).toBe("true");
  });

  it("does not render a listbox until opened", () => {
    render(<Harness />);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("marks the selected option and no other", async () => {
    render(<Harness initial="bravo" />);
    await userEvent.click(trigger());
    const selected = options().filter(
      (el) => el.getAttribute("aria-selected") === "true",
    );
    expect(selected).toHaveLength(1);
    expect(selected[0].textContent).toContain("Bravo");
  });
});

describe("Dropdown — opening by keyboard", () => {
  it("ArrowDown opens the menu focused on the first option", async () => {
    render(<Harness />);
    trigger().focus();
    await userEvent.keyboard("{ArrowDown}");
    await expectFocused(() => options()[0]);
  });

  it("ArrowUp opens the menu focused on the last option", async () => {
    render(<Harness />);
    trigger().focus();
    await userEvent.keyboard("{ArrowUp}");
    await expectFocused(() => options().at(-1));
  });
});

describe("Dropdown — navigating an open menu", () => {
  it("ArrowDown and ArrowUp move focus", async () => {
    render(<Harness />);
    trigger().focus();
    // Focus is awaited between steps, not only at the end: `userEvent`
    // dispatches a whole string within one tick, which outruns the deferred
    // focus in a way no real keyboard does. Verified against Chromium — two
    // ArrowDowns with no delay land on the second option there.
    await userEvent.keyboard("{ArrowDown}");
    await expectFocused(() => options()[0]);
    await userEvent.keyboard("{ArrowDown}");
    await expectFocused(() => options()[1]);
    await userEvent.keyboard("{ArrowUp}");
    await expectFocused(() => options()[0]);
  });

  it("wraps at both ends", async () => {
    render(<Harness />);
    trigger().focus();
    await userEvent.keyboard("{ArrowDown}{ArrowUp}");
    await expectFocused(() => options().at(-1));
  });

  it("Home and End jump to the ends", async () => {
    render(<Harness />);
    trigger().focus();
    await userEvent.keyboard("{ArrowDown}");
    await expectFocused(() => options()[0]);
    await userEvent.keyboard("{End}");
    await expectFocused(() => options().at(-1));
    await userEvent.keyboard("{Home}");
    await expectFocused(() => options()[0]);
  });

  it("typeahead jumps to the first option matching the buffer", async () => {
    // Was a `toContain("Charlie")` on the focused element's text, which the
    // trigger also satisfies. It still failed when typeahead was broken (focus
    // sits on Alpha by then, and "Alpha" does not contain "Charlie"), so it was
    // not toothless — but it could pass on a poll taken while focus was still
    // on the trigger, which is the same unsoundness that made the grouped
    // navigation test flaky. Identity against the option removes the ambiguity.
    render(<Harness />);
    trigger().focus();
    await userEvent.keyboard("{ArrowDown}");
    await expectFocused(() => options()[0]);
    await userEvent.keyboard("ch");
    await expectFocused(() => options()[2]);
  });
});

describe("Dropdown — selecting and closing", () => {
  it("selects with Enter and closes", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    trigger().focus();
    await userEvent.keyboard("{ArrowDown}");
    await expectFocused(() => options()[0]);
    await userEvent.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("alpha");
    await expectClosed();
  });

  it("returns focus to the trigger after selecting", async () => {
    render(<Harness />);
    trigger().focus();
    await userEvent.keyboard("{ArrowDown}{Enter}");
    await expectFocused(trigger);
  });

  it("Escape closes and returns focus to the trigger", async () => {
    render(<Harness />);
    trigger().focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("listbox")).toBeDefined();
    await userEvent.keyboard("{Escape}");
    await expectClosed();
    await expectFocused(trigger);
  });

  it("closes on an outside pointerdown", async () => {
    render(
      <>
        <Harness />
        <button type="button">outside</button>
      </>,
    );
    await userEvent.click(trigger());
    expect(screen.getByRole("listbox")).toBeDefined();
    await userEvent.click(screen.getByRole("button", { name: "outside" }));
    await expectClosed();
  });
});

describe("Dropdown — reset row and multi-select", () => {
  it("offers a reset row that selects null", async () => {
    const onChange = vi.fn();
    render(<Harness initial="alpha" resetLabel="Any" onChange={onChange} />);
    await userEvent.click(trigger());
    await userEvent.click(
      within(listbox()).getByRole("option", { name: /Any/ }),
    );
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("stays open when toggling a multi-select value", async () => {
    const onToggleValue = vi.fn();
    render(<Harness multiValues={["alpha"]} onToggleValue={onToggleValue} />);
    await userEvent.click(trigger());
    await userEvent.click(
      within(listbox()).getByRole("option", { name: /Bravo/ }),
    );
    expect(onToggleValue).toHaveBeenCalledWith("bravo");
    expect(screen.queryByRole("listbox")).not.toBeNull();
  });
});

describe("Dropdown — empty and disabled", () => {
  it("disables the trigger when there is nothing to choose", () => {
    render(<Harness options={[]} emptyLabel="No options" />);
    expect((trigger() as HTMLButtonElement).disabled).toBe(true);
  });

  it("disables the trigger when explicitly disabled", () => {
    render(<Harness disabled disabledReason="Not yet" />);
    expect((trigger() as HTMLButtonElement).disabled).toBe(true);
    expect(trigger().getAttribute("title")).toBe("Not yet");
  });
});

describe("Dropdown — disabled options and dead ends", () => {
  const withDisabled: DropdownOption<string>[] = [
    { value: "alpha", label: "Alpha" },
    { value: "bravo", label: "Bravo", disabled: true },
    { value: "charlie", label: "Charlie" },
  ];

  it("arrow keys step over a disabled option", async () => {
    render(<Harness options={withDisabled} />);
    trigger().focus();
    // Opening and stepping are separate keystrokes for the reason given above:
    // batched in one call, the second arrow can outrun the deferred focus and
    // be handled by the trigger again, which re-opens onto Alpha.
    await userEvent.keyboard("{ArrowDown}");
    await expectFocused(() => options()[0]);
    await userEvent.keyboard("{ArrowDown}");
    // Bravo is the disabled one, so a single step must land on Charlie.
    await expectFocused(() => options()[2]);
  });

  it("a disabled option cannot be selected by click", async () => {
    const onChange = vi.fn();
    render(<Harness options={withDisabled} onChange={onChange} />);
    await userEvent.click(trigger());
    await userEvent.click(
      within(listbox()).getByRole("option", { name: /Bravo/ }),
      { pointerEventsCheck: 0 },
    );
    expect(onChange).not.toHaveBeenCalled();
  });

  it("typeahead that matches nothing leaves focus alone", async () => {
    render(<Harness />);
    trigger().focus();
    await userEvent.keyboard("{ArrowDown}");
    await expectFocused(() => options()[0]);
    const before = document.activeElement;
    await userEvent.keyboard("zzzz");
    expect(document.activeElement).toBe(before);
  });

  it("typeahead is suppressed when the menu has a search field", async () => {
    // Those keystrokes belong to the filter. If typeahead also ran, the first
    // character would yank focus out of the input mid-word.
    render(<Harness searchPlaceholder="Search…" />);
    await userEvent.click(searchTrigger());
    await waitFor(() =>
      expect((document.activeElement as HTMLElement).tagName).toBe("INPUT"),
    );
    await userEvent.keyboard("ch");
    expect((document.activeElement as HTMLInputElement).value).toBe("ch");
  });

  it("shows the no-results message when a search matches nothing", async () => {
    render(<Harness searchPlaceholder="Search…" noResultsLabel="Nothing." />);
    await userEvent.click(searchTrigger());
    await waitFor(() =>
      expect((document.activeElement as HTMLElement).tagName).toBe("INPUT"),
    );
    await userEvent.keyboard("zzzz");
    // A listbox may hold only options, so the message sits beside it as a live
    // status — which also means screen readers hear it, where a presentational
    // node inside the list would have been silent.
    expect(screen.getByRole("status").textContent).toBe("Nothing.");
    expect(within(listbox()).queryAllByRole("option")).toHaveLength(0);
  });

  it("multiValues without onToggleValue neither crashes nor selects", async () => {
    // A caller mistake, not a supported mode — but it must fail quietly rather
    // than throwing inside a click handler.
    render(<Harness multiValues={[]} />);
    await userEvent.click(trigger());
    await userEvent.click(
      within(listbox()).getByRole("option", { name: /Alpha/ }),
    );
    expect(screen.queryByRole("listbox")).not.toBeNull();
  });

  it("renders an empty menu's label rather than an empty box", async () => {
    render(
      <Harness
        options={[]}
        emptyLabel="No options"
        topAction={{ label: "Add one", onClick: vi.fn() }}
      />,
    );
    await userEvent.click(trigger());
    expect(screen.getByRole("status").textContent).toBe("No options");
  });

  it("keeps the trigger usable when empty but a topAction exists", () => {
    render(
      <Harness
        options={[]}
        emptyLabel="No options"
        topAction={{ label: "Add one", onClick: vi.fn() }}
      />,
    );
    expect((trigger() as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("Dropdown — grouped options", () => {
  const groups = [
    { label: "First", options: [{ value: "a", label: "Apple" }] },
    { label: "Second", options: [{ value: "b", label: "Banana" }] },
  ];

  it("navigates across group boundaries as one flat list", async () => {
    // The flake this file used to show. The first wait asserted only that the
    // focused element's text contained "Apple", which the trigger satisfies on
    // its own, so under load it returned before focus had left the trigger. The
    // second ArrowDown then went to the trigger, which re-opens onto the first
    // option — landing on Apple when the test wanted Banana. Waiting on element
    // identity cannot resolve early, so the second key always reaches the list.
    render(<Harness options={[]} groups={groups} />);
    trigger().focus();
    await userEvent.keyboard("{ArrowDown}");
    await expectFocused(() => options()[0]);
    await userEvent.keyboard("{ArrowDown}");
    await expectFocused(() => options()[1]);
  });

  it("selects a value from a group", async () => {
    const onChange = vi.fn();
    render(<Harness options={[]} groups={groups} onChange={onChange} />);
    trigger().focus();
    await userEvent.keyboard("{ArrowUp}");
    await expectFocused(() => options().at(-1));
    await userEvent.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("b");
  });
});
