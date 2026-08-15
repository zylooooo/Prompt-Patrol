import { installDomStubs } from "../../../test/dom-stubs";
import DataTable, { type DataTableColumn } from "../DataTable";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

/**
 * A separate file on purpose. `useMediaQuery` caches its `MediaQueryList` in a
 * module-scope Map, so the first `matchMedia` stub a module sees is the one it
 * keeps — re-stubbing mid-file is silently ignored. Vitest gives each file a
 * fresh module registry, which is the only clean way to test the matched case.
 */

interface Row {
  id: string;
  name: string;
  score: number;
}

const COLUMNS: DataTableColumn<Row>[] = [
  {
    id: "name",
    header: "Name",
    width: "1fr",
    cell: (r) => <span>{r.name}</span>,
  },
  {
    id: "score",
    header: "Score",
    width: "1fr",
    hideWhenCompact: true,
    cell: (r) => <span>{r.score.toFixed(2)}</span>,
  },
];

beforeEach(() => installDomStubs({ matches: true }));
afterEach(cleanup);

const renderTable = () =>
  render(
    <DataTable<Row>
      columns={COLUMNS}
      rows={[{ id: "r1", name: "Ada", score: 0.9 }]}
      getRowId={(r) => r.id}
    />,
  );

describe("DataTable — narrow viewport", () => {
  it("drops a hideWhenCompact cell", () => {
    renderTable();
    expect(screen.queryByText("0.90")).toBeNull();
  });

  it("keeps the column header so the grid template stays aligned", () => {
    // The track collapses to minmax(0,0fr) rather than unmounting, which is
    // what lets the width animate instead of snapping.
    renderTable();
    expect(screen.getAllByRole("columnheader")).toHaveLength(2);
  });

  it("keeps every column that is not marked hideWhenCompact", () => {
    renderTable();
    expect(screen.getByText("Ada")).toBeDefined();
  });
});
