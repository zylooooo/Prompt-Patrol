import SupervisorsDialog from "../SupervisorsDialog";
import type { AppUser } from "../../types";
import { installDomStubs } from "../../test/dom-stubs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const showToastMock = vi.fn();
vi.mock("../../hooks/useToast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}));

const linkMock = vi.fn();
const unlinkMock = vi.fn();
vi.mock("../../hooks/useUsers", () => ({
  useLinkSupervisor: () => linkMock() as unknown,
  useUnlinkSupervisor: () => unlinkMock() as unknown,
}));

const person = (over: Partial<AppUser> & Pick<AppUser, "id">): AppUser => ({
  email: `${over.id}@smu.edu.sg`,
  name: null,
  role: "instructor",
  status: "active",
  supervisorIds: [],
  createdAt: "2026-07-01T00:00:00.000Z",
  firstLoginAt: "2026-07-02T00:00:00.000Z",
  ...over,
});

const ONE = person({ id: "i-1", name: "Teach One" });
const TWO = person({ id: "i-2", name: "Teach Two" });
const OFF = person({ id: "i-3", name: "On Leave", status: "deactivated" });
const TA = person({
  id: "ta-1",
  name: "Wei Lin",
  role: "teaching_assistant",
  supervisorIds: ["i-1"],
});

beforeEach(() => {
  installDomStubs({ matches: false });
  vi.clearAllMocks();
  linkMock.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  unlinkMock.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
});
afterEach(cleanup);

function renderDialog(assistant = TA) {
  return render(
    <SupervisorsDialog
      assistant={assistant}
      allUsers={[ONE, TWO, OFF, assistant]}
      onClose={vi.fn()}
    />,
  );
}

describe("SupervisorsDialog", () => {
  it("lists the current supervisors, each removable", () => {
    renderDialog();

    const current = screen.getByRole("list", { name: "Current supervisors" });
    expect(within(current).getByText("Teach One")).toBeTruthy();
    expect(
      within(current).getByRole("button", { name: "Remove Teach One" }),
    ).toBeTruthy();
  });

  it("says so when nobody supervises them", () => {
    renderDialog({ ...TA, supervisorIds: [] });

    expect(
      screen.getByText(
        "Nobody supervises this account, so they can't screen answers.",
      ),
    ).toBeTruthy();
  });

  it("removes one link and says whose team they left", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ ...TA, supervisorIds: [] });
    unlinkMock.mockReturnValue({ mutateAsync, isPending: false });
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Remove Teach One" }));

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        taId: "ta-1",
        instructorId: "i-1",
      }),
    );
    expect(showToastMock).toHaveBeenCalledWith(
      "Wei Lin removed from Teach One's team.",
    );
  });

  it("sends the link when Add is pressed", async () => {
    const mutateAsync = vi
      .fn()
      .mockResolvedValue({ ...TA, supervisorIds: ["i-1", "i-2"] });
    linkMock.mockReturnValue({ mutateAsync, isPending: false });
    renderDialog();

    await userEvent.click(
      screen.getByRole("combobox", { name: "Instructor to add" }),
    );
    await userEvent.click(screen.getByRole("option", { name: /Teach Two/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        taId: "ta-1",
        instructorId: "i-2",
      }),
    );
    expect(showToastMock).toHaveBeenCalledWith(
      "Wei Lin added to Teach Two's team.",
    );
  });

  it("never swallows an Add press: with nothing picked it says so", async () => {
    const mutateAsync = vi.fn();
    linkMock.mockReturnValue({ mutateAsync, isPending: false });
    renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe(
      "Choose an instructor to add first.",
    );
  });

  it("isn't held disabled by a hook that still reports pending", async () => {
    // Add is gated on the dialog's own in-flight flag, not on isPending,
    // which stays true until the roster refetch after a change settles.
    const mutateAsync = vi
      .fn()
      .mockResolvedValue({ ...TA, supervisorIds: ["i-1", "i-2"] });
    linkMock.mockReturnValue({ mutateAsync, isPending: false });
    unlinkMock.mockReturnValue({ mutateAsync: vi.fn(), isPending: true });
    renderDialog();

    await userEvent.click(
      screen.getByRole("combobox", { name: "Instructor to add" }),
    );
    await userEvent.click(screen.getByRole("option", { name: /Teach Two/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
  });

  it("offers only active instructors who aren't already linked", async () => {
    renderDialog();

    await userEvent.click(
      screen.getByRole("combobox", { name: "Instructor to add" }),
    );

    const listbox = screen.getByRole("listbox", { name: "Instructor to add" });
    expect(
      within(listbox).getByRole("option", { name: /Teach Two/ }),
    ).toBeTruthy();
    expect(
      within(listbox).queryByRole("option", { name: /Teach One/ }),
    ).toBeNull();
    expect(
      within(listbox).queryByRole("option", { name: /On Leave/ }),
    ).toBeNull();
  });
});
