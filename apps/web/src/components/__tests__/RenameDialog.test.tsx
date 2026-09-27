import RenameDialog from "../RenameDialog";
import { installDomStubs } from "../../test/dom-stubs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const showToastMock = vi.fn();
vi.mock("../../hooks/useToast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}));

const renameMock = vi.fn();
vi.mock("../../hooks/useUsers", () => ({
  useUpdateDisplayName: () => renameMock() as unknown,
}));

beforeEach(() => {
  installDomStubs({ matches: false });
  vi.clearAllMocks();
  renameMock.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
});
afterEach(cleanup);

describe("RenameDialog", () => {
  it("renames someone else and closes", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({});
    renameMock.mockReturnValue({ mutateAsync, isPending: false });
    const onClose = vi.fn();
    render(
      <RenameDialog
        id="u-1"
        email="wei@smu.edu.sg"
        currentName="Wei"
        self={false}
        onClose={onClose}
      />,
    );

    expect(screen.getByText("Rename Wei")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: " Wei Lin " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ id: "u-1", name: "Wei Lin" }),
    );
    expect(showToastMock).toHaveBeenCalledWith("Name updated.");
    expect(onClose).toHaveBeenCalled();
  });

  it("titles itself for the signed-in person", () => {
    render(
      <RenameDialog
        id="u-1"
        email="me@smu.edu.sg"
        currentName={null}
        self
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Change your name")).toBeTruthy();
    // Modal must not pull focus off the field onto its panel.
    expect(document.activeElement).toBe(screen.getByLabelText("Name"));
  });

  it("won't save a blank or unchanged name", () => {
    render(
      <RenameDialog
        id="u-1"
        email="wei@smu.edu.sg"
        currentName="Wei"
        self={false}
        onClose={vi.fn()}
      />,
    );
    const save = screen.getByRole("button", { name: "Save" });

    expect(save).toHaveProperty("disabled", true); // unchanged
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "   " },
    });
    expect(save).toHaveProperty("disabled", true);
  });
});
