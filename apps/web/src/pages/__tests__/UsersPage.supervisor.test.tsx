import UsersPage from "../UsersPage";
import type { AppUser } from "../../types";
import { MemoryRouter } from "react-router-dom";
import { installDomStubs } from "../../test/dom-stubs";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

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

vi.mock("../../hooks/useToast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));

const usersMock = vi.fn();
vi.mock("../../hooks/useUsers", () => {
  const idle = () => ({ mutateAsync: vi.fn(), isPending: false });
  return {
    useUsers: () => usersMock() as unknown,
    useCreateAccount: idle,
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
