import ConfirmAddAssistantDialog from "../ConfirmAddAssistantDialog";
import { installDomStubs } from "../../test/dom-stubs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

beforeEach(() => installDomStubs({ matches: false }));
afterEach(cleanup);

describe("ConfirmAddAssistantDialog", () => {
  it("repeats the typed email and nothing about any account", () => {
    render(
      <ConfirmAddAssistantDialog
        email="wei.lin@smu.edu.sg"
        busy={false}
        onEdit={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("wei.lin@smu.edu.sg");
    // The confirmation must not become an oracle ([0.21.0] ENUMERATION).
    expect(dialog.textContent).not.toMatch(/already|existing|pending|active/i);
  });

  it("goes back to editing or confirms", () => {
    const onEdit = vi.fn();
    const onConfirm = vi.fn();
    render(
      <ConfirmAddAssistantDialog
        email="a@smu.edu.sg"
        busy={false}
        onEdit={onEdit}
        onConfirm={onConfirm}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Edit email" }));
    fireEvent.click(screen.getByRole("button", { name: "Add to my team" }));

    expect(onEdit).toHaveBeenCalledOnce();
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("locks both buttons while adding", () => {
    render(
      <ConfirmAddAssistantDialog
        email="a@smu.edu.sg"
        busy
        onEdit={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Adding…" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(screen.getByRole("button", { name: "Edit email" })).toHaveProperty(
      "disabled",
      true,
    );
  });
});
