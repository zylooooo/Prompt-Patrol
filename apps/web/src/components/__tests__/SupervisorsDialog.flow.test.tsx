import SupervisorsDialog from "../SupervisorsDialog";
import type { AppUser } from "../../types";
import { installDomStubs } from "../../test/dom-stubs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../../hooks/useToast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));
vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      id: "admin",
      email: "a@smu.edu.sg",
      name: "A",
      role: "root_admin",
      supervisorIds: [],
    },
  }),
}));

const api = vi.hoisted(() => ({
  linkSupervisor: vi.fn(),
  unlinkSupervisor: vi.fn(),
}));
vi.mock("../../api/users", async (orig) => ({
  ...(await orig<typeof import("../../api/users")>()),
  ...api,
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
const TA = person({
  id: "ta-1",
  name: "Wei Lin",
  role: "teaching_assistant",
  supervisorIds: ["i-1"],
});

beforeEach(() => {
  installDomStubs({ matches: false });
  vi.clearAllMocks();
  api.unlinkSupervisor.mockResolvedValue({ ...TA, supervisorIds: [] });
  api.linkSupervisor.mockImplementation((_a, taId: string, id: string) =>
    Promise.resolve({ ...TA, id: taId, supervisorIds: [id] }),
  );
});
afterEach(cleanup);

describe("SupervisorsDialog with the real hooks", () => {
  it("adds a supervisor after removing the last one", async () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <SupervisorsDialog
          assistant={TA}
          allUsers={[ONE, TWO, TA]}
          onClose={vi.fn()}
        />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Remove Teach One" }));
    await screen.findByText(
      "Nobody supervises this account, so they can't screen answers.",
    );

    await user.click(
      screen.getByRole("combobox", { name: "Instructor to add" }),
    );
    await user.click(await screen.findByRole("option", { name: /Teach Two/ }));
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(api.linkSupervisor).toHaveBeenCalledWith(
        expect.anything(),
        "ta-1",
        "i-2",
      ),
    );
  });
});
