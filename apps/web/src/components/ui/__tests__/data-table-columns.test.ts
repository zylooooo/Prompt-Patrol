import { describe, expect, it } from "vitest";
import { resolveGridColumnWidth } from "../data-table-columns";

describe("resolveGridColumnWidth", () => {
  it("floors minmax(0, …fr) so columns keep a scrollable minimum", () => {
    expect(resolveGridColumnWidth("minmax(0,1.4fr)")).toBe(
      "minmax(8rem, 1.4fr)",
    );
    expect(resolveGridColumnWidth("minmax(0, 1fr)")).toBe("minmax(8rem, 1fr)");
  });

  it("leaves explicit mins and fixed tracks unchanged", () => {
    expect(resolveGridColumnWidth("minmax(5.5rem,0.7fr)")).toBe(
      "minmax(5.5rem,0.7fr)",
    );
    expect(resolveGridColumnWidth("10rem")).toBe("10rem");
  });

  it("wraps bare fr tracks with the same floor", () => {
    expect(resolveGridColumnWidth("1fr")).toBe("minmax(8rem, 1fr)");
  });

  it("treats every zero spelling as a zero min", () => {
    // The regex has to cover the units callers actually write, or a column
    // silently keeps its collapsing min and the table never scrolls.
    for (const zero of ["0", "0px", "0rem", "0em", "0fr", "0%"]) {
      expect(resolveGridColumnWidth(`minmax(${zero},2fr)`)).toBe(
        "minmax(8rem, 2fr)",
      );
    }
  });

  it("does not floor a column that already declares a fixed track", () => {
    // The escape hatch for short, bounded-content columns. An `fr` track for a
    // status chip gets floored to 8rem for ~55px of content, and under the
    // `w-max` wrapper that surplus pushes the whole table past its scrollport —
    // measured on UsersPage before its Status column became "7rem". Fixed tracks
    // must pass through untouched or that escape hatch does not exist.
    for (const fixed of ["7rem", "6rem", "6.5rem", "16.5rem", "104px"]) {
      expect(resolveGridColumnWidth(fixed)).toBe(fixed);
    }
  });

  it("does not special-case the collapsed-column track", () => {
    // Worth pinning down because it looks like a bug and is not: this floors
    // minmax(0,0fr) to 8rem, which would keep a hidden column 8rem wide. It is
    // safe only because DataTable emits that track *instead of* calling this,
    // never through it — a test in DataTable.test.tsx holds that end up.
    expect(resolveGridColumnWidth("minmax(0,0fr)")).toBe("minmax(8rem, 0fr)");
  });
});
