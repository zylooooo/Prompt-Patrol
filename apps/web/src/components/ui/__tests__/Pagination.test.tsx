import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import Pagination from "../Pagination";

const prev = () => screen.getByRole("button", { name: "Previous page" });
const next = () => screen.getByRole("button", { name: "Next page" });

/** The visible strip, as a user reads it: numbers and "…". */
const strip = () =>
  Array.from(
    screen
      .getByRole("navigation")
      .querySelectorAll("button, span[aria-hidden]"),
  )
    .map((el) => el.textContent)
    .filter((t) => t !== "");

function renderAt(
  page: number,
  totalPages: number,
  extra: Partial<Parameters<typeof Pagination>[0]> = {},
) {
  const onPageChange = vi.fn();
  render(
    <Pagination
      page={page}
      totalPages={totalPages}
      total={totalPages * 10}
      pageSize={10}
      onPageChange={onPageChange}
      {...extra}
    />,
  );
  return onPageChange;
}

afterEach(cleanup);

describe("Pagination — summary line", () => {
  it("renders nothing when there is nothing to page", () => {
    const { container } = render(
      <Pagination
        page={1}
        totalPages={0}
        total={0}
        pageSize={10}
        onPageChange={vi.fn()}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("shows the range of the current page", () => {
    renderAt(2, 3);
    expect(screen.getByRole("navigation").textContent).toContain(
      "Showing 11 – 20 of 30 results",
    );
  });

  it("caps the range at the total on a short last page", () => {
    render(
      <Pagination
        page={3}
        totalPages={3}
        total={25}
        pageSize={10}
        onPageChange={vi.fn()}
        itemNoun="checks"
      />,
    );
    expect(screen.getByRole("navigation").textContent).toContain(
      "21 – 25 of 25 checks",
    );
  });

  it("shows a single number, not 'n – n', when the range is one item", () => {
    render(
      <Pagination
        page={1}
        totalPages={1}
        total={1}
        pageSize={10}
        onPageChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("navigation").textContent).not.toContain("–");
  });

  it("hides the pager when everything fits on one page", () => {
    renderAt(1, 1);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("Pagination — page strip", () => {
  it("lists every page when there are seven or fewer", () => {
    renderAt(1, 7);
    expect(strip()).toEqual(["1", "2", "3", "4", "5", "6", "7"]);
  });

  it("collapses the middle with ellipses past seven", () => {
    renderAt(5, 10);
    expect(strip()).toEqual(["1", "…", "4", "5", "6", "…", "10"]);
  });

  it("fills a one-page gap with the number rather than an ellipsis", () => {
    // An ellipsis standing in for exactly one page saves no space and hides it.
    renderAt(3, 10);
    expect(strip()).toEqual(["1", "2", "3", "4", "…", "10"]);
  });

  it("marks only the current page, and it cannot be clicked", () => {
    renderAt(2, 3);
    const current = screen.getByRole("button", {
      name: "Page 2, current page",
    });
    expect(current.getAttribute("aria-current")).toBe("page");
    expect(current.hasAttribute("disabled")).toBe(true);
    expect(document.querySelectorAll("[aria-current]")).toHaveLength(1);
  });
});

describe("Pagination — boundaries", () => {
  it("disables Previous on the first page and Next on the last", () => {
    renderAt(1, 3);
    expect(prev().hasAttribute("disabled")).toBe(true);
    expect(next().hasAttribute("disabled")).toBe(false);

    cleanup();
    renderAt(3, 3);
    expect(prev().hasAttribute("disabled")).toBe(false);
    expect(next().hasAttribute("disabled")).toBe(true);
  });

  it("clamps an out-of-range page instead of showing a bogus range", () => {
    // A stale ?page=9 after rows were deleted must not read "Showing 81 – 30".
    renderAt(9, 3);
    expect(screen.getByRole("navigation").textContent).toContain("21 – 30");
    expect(
      screen.getByRole("button", { name: "Page 3, current page" }),
    ).toBeDefined();
  });
});

describe("Pagination — navigation", () => {
  it("moves with Previous, Next and a page number", async () => {
    const onPageChange = renderAt(2, 5);
    await userEvent.click(prev());
    await userEvent.click(next());
    await userEvent.click(screen.getByRole("button", { name: "Go to page 4" }));
    expect(onPageChange.mock.calls).toEqual([[1], [3], [4]]);
  });

  it("goes nowhere while disabled", async () => {
    const onPageChange = renderAt(2, 5, { disabled: true });
    await userEvent.click(next(), { pointerEventsCheck: 0 });
    await userEvent.click(
      screen.getByRole("button", { name: "Go to page 4" }),
      {
        pointerEventsCheck: 0,
      },
    );
    expect(onPageChange).not.toHaveBeenCalled();
  });
});
