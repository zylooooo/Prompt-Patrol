import UsersPage from "../UsersPage";
import type { AppUser } from "../../types";
import { MemoryRouter } from "react-router-dom";
import { installDomStubs } from "../../test/dom-stubs";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

/**
 * The defect this covers: the roster's supervisor column was resolved through a
 * table of links kept in this browser's localStorage. A teaching assistant the
 * server had provisioned under an instructor was never in that table, so the
 * roster called them "Unassigned" - to the admin, and to the very instructor who
 * supervises them. It reads the column the server sends now.
 */

const useAuthMock = vi.fn();
vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => useAuthMock() as unknown,
}));

const showToastMock = vi.fn();
vi.mock("../../hooks/useToast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}));

const usersMock = vi.fn();
const resendMock = vi.fn();
const createMock = vi.fn();
vi.mock("../../hooks/useUsers", () => {
  const idle = () => ({ mutateAsync: vi.fn(), isPending: false });
  return {
    useResendInvite: () => resendMock() as unknown,
    useUsers: () => usersMock() as unknown,
    useCreateAccount: () => createMock() as unknown,
    useSetUserActive: idle,
    useDeleteUser: idle,
    useSetSupervisor: idle,
    useDeactivateInstructor: idle,
  };
});

const user = (over: Partial<AppUser> & Pick<AppUser, "id">): AppUser => ({
  email: `${over.id}@smu.edu.sg`,
  name: null,
  role: "teaching_assistant",
  status: "active",
  provisionedBy: null,
  createdAt: "2026-07-01T00:00:00.000Z",
  firstLoginAt: "2026-07-02T00:00:00.000Z",
  ...over,
});

const INSTRUCTOR = user({
  id: "inst-1",
  name: "Teach One",
  role: "instructor",
});
const ASSIGNED = user({
  id: "ta-assigned",
  name: "Assigned Assistant",
  provisionedBy: "inst-1",
});
const UNASSIGNED = user({ id: "ta-floating", name: "Floating Assistant" });

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <UsersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  installDomStubs({ matches: false });
  vi.clearAllMocks();
  localStorage.clear();
  useAuthMock.mockReturnValue({
    user: {
      email: "admin@smu.edu.sg",
      role: "root_admin",
      provisionedBy: null,
    },
    isPending: false,
    isError: false,
    error: null,
  });
  usersMock.mockReturnValue({
    data: [INSTRUCTOR, ASSIGNED, UNASSIGNED],
    isPending: false,
  });
  resendMock.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  createMock.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
});
afterEach(() => {
  cleanup();
  localStorage.clear();
});

/** The row a person occupies, so a cell is read against its own account. */
async function rowFor(name: string): Promise<HTMLElement> {
  const cell = await waitFor(() => screen.getByText(name));
  const row = cell.closest("[role='row']");
  if (!(row instanceof HTMLElement)) throw new Error(`no row for ${name}`);
  return row;
}

describe("UsersPage — when the roster fails to load", () => {
  it("says so instead of claiming no accounts match", async () => {
    usersMock.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
      refetch: vi.fn(),
    });

    renderPage();

    await waitFor(() => screen.getByText("Could not load accounts"));
    expect(screen.queryByText("No accounts match this filter.")).toBeNull();
  });

  it("keeps the roster on screen when only a refetch failed", async () => {
    usersMock.mockReturnValue({
      data: [INSTRUCTOR],
      isPending: false,
      isError: true,
      refetch: vi.fn(),
    });

    renderPage();

    await rowFor("Teach One");
    expect(screen.queryByText("Could not load accounts")).toBeNull();
  });
});

describe("UsersPage — the supervisor column", () => {
  it("names the instructor the server recorded", async () => {
    renderPage();

    const row = await rowFor("Assigned Assistant");

    expect(row.textContent).toContain("Teach One");
    expect(row.textContent).not.toContain("Unassigned");
  });

  it("says Unassigned for an assistant the server left unassigned", async () => {
    renderPage();

    const row = await rowFor("Floating Assistant");

    expect(row.textContent).toContain("Unassigned");
  });

  it("does not consult anything this browser stored", async () => {
    // The old lookup answered from localStorage, so an empty one meant everybody
    // read as unassigned. An empty one has to change nothing now.
    localStorage.clear();

    renderPage();

    const row = await rowFor("Assigned Assistant");

    expect(row.textContent).toContain("Teach One");
  });

  it("leaves the supervisor cell blank for an instructor", async () => {
    renderPage();

    // By email: the name appears twice over, once as this row and once as the
    // assistant's supervisor, which is the whole point of the column.
    const row = await rowFor("inst-1@smu.edu.sg");

    expect(row.textContent).toContain("·");
    expect(row.textContent).not.toContain("Unassigned");
  });
});

describe("UsersPage - finding accounts", () => {
  it("counts each filter and searches by name or email", async () => {
    renderPage();

    await rowFor("Assigned Assistant");
    expect(screen.getByRole("radio", { name: "All 3" })).toBeTruthy();
    expect(screen.getByRole("radio", { name: "Unassigned 1" })).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Search accounts"), {
      target: { value: "floating" },
    });
    await rowFor("Floating Assistant");
    expect(screen.queryByText("Assigned Assistant")).toBeNull();
  });

  it("offers a way out of an empty search", async () => {
    renderPage();
    await rowFor("Assigned Assistant");

    fireEvent.change(screen.getByLabelText("Search accounts"), {
      target: { value: "zzz" },
    });
    await waitFor(() => screen.getByText('No accounts match "zzz".'));
    fireEvent.click(screen.getByRole("button", { name: "Show all accounts" }));
    await rowFor("Assigned Assistant");
  });
});

describe("UsersPage - pending invites", () => {
  const PENDING = user({
    id: "ta-new",
    name: "New Assistant",
    firstLoginAt: null,
  });

  it("counts and filters pending accounts", async () => {
    usersMock.mockReturnValue({
      data: [INSTRUCTOR, ASSIGNED, PENDING],
      isPending: false,
    });
    renderPage();

    await rowFor("New Assistant");
    fireEvent.click(screen.getByRole("radio", { name: "Pending 1" }));

    await rowFor("New Assistant");
    expect(screen.queryByText("Assigned Assistant")).toBeNull();
  });

  it("offers Resend invite inline, only on a pending row, and reports success", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(PENDING);
    resendMock.mockReturnValue({ mutateAsync, isPending: false });
    usersMock.mockReturnValue({
      data: [INSTRUCTOR, ASSIGNED, PENDING],
      isPending: false,
    });
    renderPage();

    const row = await rowFor("New Assistant");
    fireEvent.click(within(row).getByRole("button", { name: "Resend invite" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith("ta-new"));
    expect(showToastMock).toHaveBeenCalledWith(
      "Invite resent to ta-new@smu.edu.sg.",
    );

    const signedIn = await rowFor("Assigned Assistant");
    expect(
      within(signedIn).queryByRole("button", { name: "Resend invite" }),
    ).toBeNull();
    expect(
      within(signedIn).getByRole("button", { name: "Deactivate" }),
    ).toBeTruthy();
  });

  it("moves Deactivate into the menu on a pending row", async () => {
    usersMock.mockReturnValue({
      data: [INSTRUCTOR, PENDING],
      isPending: false,
    });
    renderPage();

    const row = await rowFor("New Assistant");
    expect(
      within(row).queryByRole("button", { name: "Deactivate" }),
    ).toBeNull();
    fireEvent.click(
      within(row).getByRole("button", {
        name: "More actions for New Assistant",
      }),
    );
    expect(
      await screen.findByRole("menuitem", { name: "Deactivate" }),
    ).toBeTruthy();
  });

  it("says the invite wasn't sent when the resend fails", async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error("boom"));
    resendMock.mockReturnValue({ mutateAsync, isPending: false });
    usersMock.mockReturnValue({
      data: [INSTRUCTOR, PENDING],
      isPending: false,
    });
    renderPage();

    const row = await rowFor("New Assistant");
    fireEvent.click(within(row).getByRole("button", { name: "Resend invite" }));

    await waitFor(() =>
      expect(showToastMock).toHaveBeenCalledWith(
        "Couldn't resend the invite to ta-new@smu.edu.sg. Try again.",
        { tone: "error" },
      ),
    );
  });
});

describe("UsersPage - email typo check", () => {
  async function fill(email: string) {
    fireEvent.change(screen.getByLabelText(/SMU email/), {
      target: { value: email },
    });
    fireEvent.click(screen.getByRole("combobox", { name: "Role" }));
    fireEvent.click(
      await screen.findByRole("option", { name: "Teaching Assistant" }),
    );
  }

  it("pauses once on a near-miss domain and lets the admin keep it", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(user({ id: "x" }));
    createMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();
    await fill("ann@gmial.com");

    fireEvent.click(screen.getByRole("button", { name: "Add account" }));
    await screen.findByText(/Did you mean/);
    expect(mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Keep as typed" }));
    expect(screen.queryByText(/Did you mean/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Add account" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
  });

  it("swaps in the suggestion", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(user({ id: "x" }));
    createMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();
    await fill("ann@gmial.com");

    fireEvent.click(screen.getByRole("button", { name: "Add account" }));
    fireEvent.click(await screen.findByRole("button", { name: /^Use / }));

    expect(screen.getByLabelText(/SMU email/)).toHaveProperty(
      "value",
      "ann@gmail.com",
    );
  });

  it("pauses again if the address is edited and then restored", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(user({ id: "x" }));
    createMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();
    await fill("ann@gmial.com");
    const submit = () =>
      fireEvent.click(screen.getByRole("button", { name: "Add account" }));

    submit();
    fireEvent.click(
      await screen.findByRole("button", { name: "Keep as typed" }),
    );
    fireEvent.change(screen.getByLabelText(/SMU email/), {
      target: { value: "ann@gmial.co" },
    });
    fireEvent.change(screen.getByLabelText(/SMU email/), {
      target: { value: "ann@gmial.com" },
    });
    submit();

    await screen.findByText(/Did you mean/);
    expect(mutateAsync).not.toHaveBeenCalled();
  });
});
