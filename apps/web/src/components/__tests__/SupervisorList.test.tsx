import SupervisorList from "../SupervisorList";
import { installDomStubs } from "../../test/dom-stubs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

beforeEach(() => installDomStubs({ matches: false }));
afterEach(cleanup);

describe("SupervisorList", () => {
  it("shows a single supervisor as plain text, with nothing to open", () => {
    render(<SupervisorList names={["Teach One"]} onEdit={vi.fn()} />);

    expect(screen.getByText("Teach One")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("names every supervisor on the +N chip for assistive tech", () => {
    render(
      <SupervisorList
        names={["Teach One", "Teach Two", "Teach Three"]}
        onEdit={vi.fn()}
      />,
    );

    const chip = screen.getByRole("button", {
      name: "Supervised by Teach One, Teach Two and Teach Three",
    });
    expect(chip.textContent).toBe("+2");
    expect(chip.getAttribute("aria-expanded")).toBe("false");
  });

  it("opens the full list, and Escape closes it back onto the chip", async () => {
    const user = userEvent.setup();
    render(
      <SupervisorList names={["Teach One", "Teach Two"]} onEdit={vi.fn()} />,
    );
    const chip = screen.getByRole("button", { name: /Supervised by/ });

    await user.click(chip);
    const list = screen.getByRole("dialog", { name: "Supervised by 2" });
    expect(list.textContent).toContain("Teach One");
    expect(list.textContent).toContain("Teach Two");
    expect(chip.getAttribute("aria-expanded")).toBe("true");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(chip));
  });

  it("hands off to the editor from the list", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    render(
      <SupervisorList names={["Teach One", "Teach Two"]} onEdit={onEdit} />,
    );

    await user.click(screen.getByRole("button", { name: /Supervised by/ }));
    await user.click(screen.getByRole("button", { name: "Edit supervisors…" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(onEdit).toHaveBeenCalledOnce());
  });
});
