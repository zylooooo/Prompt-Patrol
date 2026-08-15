import userEvent from "@testing-library/user-event";
import { installDomStubs } from "../../../test/dom-stubs";
import DataTable, { type DataTableColumn } from "../DataTable";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

interface Row {
  id: string;
  name: string;
  score: number;
}

const ROWS: Row[] = [
  { id: "r1", name: "Ada", score: 0.1 },
  { id: "r2", name: "Grace", score: 0.9 },
];

const COLUMNS: DataTableColumn<Row>[] = [
  {
    id: "name",
    header: "Name",
    width: "minmax(0,1fr)",
    sortKey: "name",
    cell: (r) => <span>{r.name}</span>,
  },
  {
    id: "score",
    header: "Score",
    width: "minmax(0,1fr)",
    hideWhenCompact: true,
    cell: (r) => <span>{r.score.toFixed(2)}</span>,
  },
];

const renderTable = (
  props: Partial<Parameters<typeof DataTable<Row>>[0]> = {},
) =>
  render(
    <DataTable<Row>
      columns={COLUMNS}
      rows={ROWS}
      getRowId={(r) => r.id}
      {...props}
    />,
  );

beforeEach(() => installDomStubs());
afterEach(cleanup);

describe("DataTable — semantics", () => {
  it("exposes ARIA table roles despite not being <table> markup", () => {
    renderTable();
    expect(screen.getByRole("table")).toBeDefined();
    expect(screen.getAllByRole("columnheader")).toHaveLength(2);
    // one header row + one row per record
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("renders each column's cell for each row", () => {
    renderTable();
    expect(screen.getByText("Ada")).toBeDefined();
    expect(screen.getByText("0.90")).toBeDefined();
  });
});

describe("DataTable — states", () => {
  it("shows the loading affordance only while there are no rows", () => {
    const { rerender } = renderTable({ rows: [], isLoading: true });
    expect(screen.getByRole("status")).toBeDefined();

    rerender(
      <DataTable<Row>
        columns={COLUMNS}
        rows={ROWS}
        getRowId={(r) => r.id}
        isLoading
      />,
    );
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows the empty state only when not loading and there are no rows", () => {
    const empty = <p>Nothing here</p>;
    const { rerender } = renderTable({
      rows: [],
      isLoading: true,
      emptyState: empty,
    });
    expect(screen.queryByText("Nothing here")).toBeNull();

    rerender(
      <DataTable<Row>
        columns={COLUMNS}
        rows={[]}
        getRowId={(r) => r.id}
        emptyState={empty}
      />,
    );
    expect(screen.getByText("Nothing here")).toBeDefined();
  });

  it("hides the empty state once rows arrive", () => {
    renderTable({ emptyState: <p>Nothing here</p> });
    expect(screen.queryByText("Nothing here")).toBeNull();
  });

  it("renders a footer when given one", () => {
    renderTable({ footer: <span>2 results</span> });
    expect(screen.getByText("2 results")).toBeDefined();
  });
});

describe("DataTable — selection", () => {
  it("calls onSelect with the row id", async () => {
    const onSelect = vi.fn();
    renderTable({ onSelect });
    await userEvent.click(screen.getByText("Ada"));
    expect(onSelect).toHaveBeenCalledWith("r1");
  });

  it("marks the selected row and no other", () => {
    renderTable({ selectedId: "r2", onSelect: vi.fn() });
    const selected = screen
      .getAllByRole("row")
      .filter((el) => el.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(1);
    expect(within(selected[0]).getByText("Grace")).toBeDefined();
  });

  it("does not make rows clickable without onSelect", async () => {
    const onSelect = vi.fn();
    renderTable();
    await userEvent.click(screen.getByText("Ada"));
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe("DataTable — sorting", () => {
  it("only makes a column sortable when it has a sortKey and an onSort", () => {
    renderTable();
    // sortKey alone is not enough — without onSort there is no control
    expect(screen.queryByRole("button", { name: "Name" })).toBeNull();

    cleanup();
    renderTable({ onSort: vi.fn() });
    expect(screen.getByRole("button", { name: "Name" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "Score" })).toBeNull();
  });

  it("reports sort direction through aria-sort", () => {
    renderTable({ onSort: vi.fn(), sort: "name", order: "asc" });
    const [nameHeader, scoreHeader] = screen.getAllByRole("columnheader");
    expect(nameHeader.getAttribute("aria-sort")).toBe("ascending");
    // an unsorted-but-sortable column reports "none"; a plain column reports nothing
    expect(scoreHeader.getAttribute("aria-sort")).toBeNull();
  });

  it("marks a sortable-but-inactive column as aria-sort=none", () => {
    renderTable({ onSort: vi.fn(), sort: null });
    const [nameHeader] = screen.getAllByRole("columnheader");
    expect(nameHeader.getAttribute("aria-sort")).toBe("none");
  });

  it("passes the column's sortKey to onSort", async () => {
    const onSort = vi.fn();
    renderTable({ onSort });
    await userEvent.click(screen.getByRole("button", { name: "Name" }));
    expect(onSort).toHaveBeenCalledWith("name");
  });
});

describe("DataTable — compact collapsing", () => {
  // Viewport-driven collapsing lives in DataTable.compact.test.tsx: the
  // `matchMedia` stub has to be in place before the first render in the module,
  // because `useMediaQuery` caches its MediaQueryList at module scope.
  it("honours an explicit isCompact regardless of viewport", () => {
    renderTable({ isCompact: true });
    expect(screen.queryByText("0.90")).toBeNull();
    // the header cell survives so the grid template stays aligned
    expect(screen.getAllByRole("columnheader")).toHaveLength(2);
  });

  it("keeps non-compact columns visible when compact", () => {
    renderTable({ isCompact: true });
    expect(screen.getByText("Ada")).toBeDefined();
  });
});

describe("DataTable — exiting rows", () => {
  it("ignores clicks on a row that is animating out", async () => {
    // The row is still mounted for 250ms while its height collapses; a click
    // landing in that window must not re-select a record being removed.
    const onSelect = vi.fn();
    renderTable({ onSelect, exitingRowIds: new Set(["r1"]) });
    await userEvent.click(screen.getByText("Ada"), { pointerEventsCheck: 0 });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("still routes clicks on rows that are not exiting", async () => {
    const onSelect = vi.fn();
    renderTable({ onSelect, exitingRowIds: new Set(["r1"]) });
    await userEvent.click(screen.getByText("Grace"));
    expect(onSelect).toHaveBeenCalledWith("r2");
  });
});

describe("DataTable — degenerate input", () => {
  it("renders nothing but the header for zero rows and no empty state", () => {
    renderTable({ rows: [] });
    expect(screen.getAllByRole("row")).toHaveLength(1);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("renders a header-only table when given no columns", () => {
    render(<DataTable<Row> columns={[]} rows={ROWS} getRowId={(r) => r.id} />);
    expect(screen.queryAllByRole("columnheader")).toHaveLength(0);
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("selects by id, not by position, when ids repeat", () => {
    // A duplicate id is caller error, but the selection must not silently
    // apply to only one of them or to the wrong one.
    const dupes: Row[] = [
      { id: "same", name: "First", score: 0 },
      { id: "same", name: "Second", score: 1 },
    ];
    render(
      <DataTable<Row>
        columns={COLUMNS}
        rows={dupes}
        getRowId={(r) => r.id}
        selectedId="same"
        onSelect={vi.fn()}
      />,
    );
    const selected = screen
      .getAllByRole("row")
      .filter((el) => el.getAttribute("aria-selected") === "true");
    expect(selected).toHaveLength(2);
  });

  it("shows the loading label it was given", () => {
    renderTable({ rows: [], isLoading: true, loadingLabel: "Fetching…" });
    expect(screen.getByRole("status").textContent).toContain("Fetching…");
  });
});
