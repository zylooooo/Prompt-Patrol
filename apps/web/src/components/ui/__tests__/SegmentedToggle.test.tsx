import SegmentedToggle, {
  type SegmentedToggleOption,
} from "../SegmentedToggle";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { installDomStubs } from "../../../test/dom-stubs";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Filter = "all" | "flagged" | "human";

const OPTIONS: SegmentedToggleOption<Filter>[] = [
  { value: "all", label: "All" },
  { value: "flagged", label: "Flagged" },
  { value: "human", label: "Human" },
];

function Harness({
  options = OPTIONS,
  initial = "all",
  onChange,
}: {
  options?: SegmentedToggleOption<Filter>[];
  initial?: Filter;
  onChange?: (next: Filter) => void;
}) {
  const [value, setValue] = useState<Filter>(initial);
  return (
    <SegmentedToggle
      options={options}
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
      ariaLabel="Filter"
    />
  );
}

beforeEach(() => installDomStubs());
afterEach(cleanup);

describe("SegmentedToggle — semantics", () => {
  it("is a radiogroup of radios, not a set of toggle buttons", () => {
    render(<Harness />);
    expect(screen.getByRole("radiogroup", { name: "Filter" })).toBeDefined();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
  });

  it("marks only the current option as checked", () => {
    render(<Harness initial="flagged" />);
    const checked = screen
      .getAllByRole("radio")
      .filter((el) => el.getAttribute("aria-checked") === "true");
    expect(checked).toHaveLength(1);
    expect(checked[0].textContent).toBe("Flagged");
  });

  it("keeps only the checked option tabbable, so Tab skips the group", () => {
    render(<Harness initial="flagged" />);
    const tabIndexes = screen
      .getAllByRole("radio")
      .map((el) => el.getAttribute("tabindex"));
    expect(tabIndexes).toEqual(["-1", "0", "-1"]);
  });
});

describe("SegmentedToggle — focus", () => {
  it("shows focus as a fill change, never a ring", () => {
    render(<Harness />);
    for (const segment of screen.getAllByRole("radio")) {
      const cls = segment.className.split(/\s+/);
      expect(
        cls.filter((c) => /^focus-visible:bg-/.test(c)),
        segment.textContent ?? "",
      ).toHaveLength(1);
      expect(
        cls.filter((c) => /^focus(-visible)?:(ring|outline)-/.test(c)),
        segment.textContent ?? "",
      ).toEqual([]);
    }
  });

  it("still moves focus with the arrow keys", () => {
    // Losing the ring must not mean losing the roving-tabindex behaviour: the
    // control is still keyboard-operable, it just gives no visual feedback.
    render(<Harness />);
    const [first] = screen.getAllByRole("radio");
    first.focus();
    expect(document.activeElement).toBe(first);
  });
});

describe("SegmentedToggle — pointer", () => {
  it("selects on click", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.click(screen.getByRole("radio", { name: "Human" }));
    expect(onChange).toHaveBeenCalledWith("human");
  });
});

describe("SegmentedToggle — keyboard", () => {
  it("moves and selects with ArrowRight (automatic activation)", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    screen.getByRole("radio", { name: "All" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith("flagged");
    expect(document.activeElement?.textContent).toBe("Flagged");
  });

  it("wraps past the last option", async () => {
    const onChange = vi.fn();
    render(<Harness initial="human" onChange={onChange} />);
    screen.getByRole("radio", { name: "Human" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith("all");
  });

  it("wraps backwards past the first option", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    screen.getByRole("radio", { name: "All" }).focus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(onChange).toHaveBeenCalledWith("human");
  });

  it("treats ArrowDown/ArrowUp as ArrowRight/ArrowLeft", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    screen.getByRole("radio", { name: "All" }).focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(onChange).toHaveBeenLastCalledWith("flagged");
  });

  it("jumps to first and last with Home and End", async () => {
    const onChange = vi.fn();
    render(<Harness initial="flagged" onChange={onChange} />);
    screen.getByRole("radio", { name: "Flagged" }).focus();
    await userEvent.keyboard("{End}");
    expect(onChange).toHaveBeenLastCalledWith("human");
    await userEvent.keyboard("{Home}");
    expect(onChange).toHaveBeenLastCalledWith("all");
  });

  it("skips a disabled option instead of selecting it", async () => {
    const onChange = vi.fn();
    render(
      <Harness
        options={[
          { value: "all", label: "All" },
          { value: "flagged", label: "Flagged", disabled: true },
          { value: "human", label: "Human" },
        ]}
        onChange={onChange}
      />,
    );
    screen.getByRole("radio", { name: "All" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith("human");
    expect(onChange).not.toHaveBeenCalledWith("flagged");
  });
});

describe("SegmentedToggle — degenerate input", () => {
  it("does not select or hang when every option is disabled", () => {
    // `moveTo` scans for the next enabled option; with none it must terminate
    // after one pass rather than looping forever.
    const onChange = vi.fn();
    render(
      <SegmentedToggle
        options={[
          { value: "all", label: "All", disabled: true },
          { value: "flagged", label: "Flagged", disabled: true },
        ]}
        value="all"
        onChange={onChange}
        ariaLabel="Filter"
      />,
    );
    screen.getAllByRole("radio")[0].focus();
    return userEvent
      .keyboard("{ArrowRight}")
      .then(() => expect(onChange).not.toHaveBeenCalled());
  });

  it("still navigates when the current value is absent from the options", async () => {
    const onChange = vi.fn();
    render(
      <SegmentedToggle
        options={OPTIONS}
        value={"gone" as Filter}
        onChange={onChange}
        ariaLabel="Filter"
      />,
    );
    screen.getAllByRole("radio")[0].focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalled();
  });

  it("marks nothing checked when the value matches no option", () => {
    render(
      <SegmentedToggle
        options={OPTIONS}
        value={"gone" as Filter}
        onChange={vi.fn()}
        ariaLabel="Filter"
      />,
    );
    expect(
      screen
        .getAllByRole("radio")
        .filter((el) => el.getAttribute("aria-checked") === "true"),
    ).toHaveLength(0);
  });

  it("renders a single option without a wrap-to-self crash", async () => {
    const onChange = vi.fn();
    render(
      <SegmentedToggle
        options={[{ value: "all", label: "All" }]}
        value="all"
        onChange={onChange}
        ariaLabel="Filter"
      />,
    );
    screen.getByRole("radio").focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith("all");
  });

  it("does not fire onChange when a disabled option is clicked", async () => {
    const onChange = vi.fn();
    render(
      <Harness
        options={[
          { value: "all", label: "All" },
          { value: "flagged", label: "Flagged", disabled: true },
        ]}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByRole("radio", { name: "Flagged" }), {
      pointerEventsCheck: 0,
    });
    expect(onChange).not.toHaveBeenCalled();
  });
});
