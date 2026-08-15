import { useState } from "react";
import Tabs, { type TabOption } from "../Tabs";
import userEvent from "@testing-library/user-event";
import { installDomStubs } from "../../../test/dom-stubs";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type TabId = "single" | "batch" | "history";

const TABS: TabOption<TabId>[] = [
  { value: "single", label: "Single answer" },
  { value: "batch", label: "Batch upload" },
  { value: "history", label: "History" },
];

function Harness({
  initial = "single",
  onChange,
}: {
  initial?: TabId;
  onChange?: (next: TabId) => void;
}) {
  const [value, setValue] = useState<TabId>(initial);
  return (
    <>
      <Tabs
        tabs={TABS}
        value={value}
        onChange={(next) => {
          setValue(next);
          onChange?.(next);
        }}
        ariaLabel="Check mode"
      />
      <div
        role="tabpanel"
        id={`panel-${value}`}
        aria-labelledby={`tab-${value}`}
      >
        panel for {value}
      </div>
    </>
  );
}

beforeEach(() => installDomStubs());
afterEach(cleanup);

describe("Tabs — semantics", () => {
  it("is a tablist of tabs", () => {
    render(<Harness />);
    expect(screen.getByRole("tablist", { name: "Check mode" })).toBeDefined();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
  });

  it("marks exactly one tab selected", () => {
    render(<Harness initial="batch" />);
    const selected = screen.getAllByRole("tab", { selected: true });
    expect(selected).toHaveLength(1);
    expect(selected[0].textContent).toBe("Batch upload");
  });

  it("wires each tab to its panel through id and aria-controls", () => {
    render(<Harness initial="batch" />);
    const tab = screen.getByRole("tab", { selected: true });
    expect(tab.id).toBe("tab-batch");
    expect(tab.getAttribute("aria-controls")).toBe("panel-batch");
    // The contract only holds if a panel actually answers to that id.
    expect(document.getElementById("panel-batch")).not.toBeNull();
  });

  it("keeps only the selected tab tabbable", () => {
    render(<Harness initial="batch" />);
    expect(
      screen.getAllByRole("tab").map((el) => el.getAttribute("tabindex")),
    ).toEqual(["-1", "0", "-1"]);
  });
});

describe("Tabs — keyboard", () => {
  it("moves and activates with ArrowRight", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    screen.getByRole("tab", { name: "Single answer" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenCalledWith("batch");
    expect(document.activeElement?.textContent).toBe("Batch upload");
  });

  it("wraps in both directions", async () => {
    const onChange = vi.fn();
    render(<Harness initial="history" onChange={onChange} />);
    screen.getByRole("tab", { name: "History" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onChange).toHaveBeenLastCalledWith("single");
    await userEvent.keyboard("{ArrowLeft}");
    expect(onChange).toHaveBeenLastCalledWith("history");
  });

  it("jumps to first and last with Home and End", async () => {
    const onChange = vi.fn();
    render(<Harness initial="batch" onChange={onChange} />);
    screen.getByRole("tab", { name: "Batch upload" }).focus();
    await userEvent.keyboard("{End}");
    expect(onChange).toHaveBeenLastCalledWith("history");
    await userEvent.keyboard("{Home}");
    expect(onChange).toHaveBeenLastCalledWith("single");
  });

  it("selects on click", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(onChange).toHaveBeenCalledWith("history");
  });
});

describe("Tabs — degenerate input", () => {
  it("wraps a single tab onto itself without throwing", async () => {
    const onChange = vi.fn();
    render(
      <Tabs
        tabs={[{ value: "only", label: "Only" }]}
        value="only"
        onChange={onChange}
        ariaLabel="Solo"
      />,
    );
    screen.getByRole("tab").focus();
    await userEvent.keyboard("{ArrowRight}{ArrowLeft}{Home}{End}");
    expect(onChange).toHaveBeenCalledWith("only");
  });

  it("selects nothing when the value matches no tab", () => {
    render(
      <Tabs
        tabs={TABS}
        value={"gone" as TabId}
        onChange={vi.fn()}
        ariaLabel="Check mode"
      />,
    );
    expect(screen.queryAllByRole("tab", { selected: true })).toHaveLength(0);
  });

  it("leaves the whole bar untabbable when nothing is selected", () => {
    // Every tab falls to tabIndex -1, so Tab skips the bar entirely rather
    // than landing on an arbitrary tab.
    render(
      <Tabs
        tabs={TABS}
        value={"gone" as TabId}
        onChange={vi.fn()}
        ariaLabel="Check mode"
      />,
    );
    expect(
      screen.getAllByRole("tab").map((el) => el.getAttribute("tabindex")),
    ).toEqual(["-1", "-1", "-1"]);
  });

  it("ignores keys it does not handle", async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    screen.getByRole("tab", { name: "Single answer" }).focus();
    await userEvent.keyboard("{ArrowUp}{ArrowDown}{PageUp}x");
    expect(onChange).not.toHaveBeenCalled();
  });
});
