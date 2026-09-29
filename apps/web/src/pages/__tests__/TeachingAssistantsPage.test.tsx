import TeachingAssistantsPage from "../TeachingAssistantsPage";
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

const showToastMock = vi.fn();
vi.mock("../../hooks/useToast", () => ({
  useToast: () => ({ showToast: showToastMock }),
}));

const assistantsMock = vi.fn();
const resendMock = vi.fn();
const addMock = vi.fn();
const unlinkMock = vi.fn();
vi.mock("../../hooks/useUsers", () => ({
  useMyAssistants: () => assistantsMock() as unknown,
  useAddTeachingAssistant: () => addMock() as unknown,
  useUnlinkSupervisor: () => unlinkMock() as unknown,
  useResendInvite: () => resendMock() as unknown,
}));

vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => ({
    user: {
      id: "inst-1",
      email: "inst-1@smu.edu.sg",
      name: "Teach One",
      role: "instructor",
      supervisorIds: [],
    },
  }),
}));

const user = (over: Partial<AppUser> & Pick<AppUser, "id">): AppUser => ({
  email: `${over.id}@smu.edu.sg`,
  name: null,
  role: "teaching_assistant",
  status: "active",
  supervisorIds: ["inst-1"],
  createdAt: "2026-07-01T00:00:00.000Z",
  firstLoginAt: "2026-07-02T00:00:00.000Z",
  ...over,
});

const PENDING = user({
  id: "ta-new",
  name: "New Assistant",
  firstLoginAt: null,
});
const SIGNED_IN = user({ id: "ta-old", name: "Signed In Assistant" });

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TeachingAssistantsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function rowFor(name: string): Promise<HTMLElement> {
  const cell = await waitFor(() => screen.getByText(name));
  const row = cell.closest("[role='row']");
  if (!(row instanceof HTMLElement)) throw new Error(`no row for ${name}`);
  return row;
}

async function openMenuItem(row: HTMLElement, name: string, item: string) {
  fireEvent.click(
    within(row).getByRole("button", { name: `More actions for ${name}` }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: item }));
}

beforeEach(() => {
  installDomStubs({ matches: false });
  vi.clearAllMocks();
  assistantsMock.mockReturnValue({
    data: [PENDING, SIGNED_IN],
    isPending: false,
    isError: false,
  });
  resendMock.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  addMock.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  unlinkMock.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
});
afterEach(cleanup);

describe("TeachingAssistantsPage - pending invites", () => {
  it("resends the invite for a pending assistant and says so", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(PENDING);
    resendMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();

    const row = await rowFor("New Assistant");
    await openMenuItem(row, "New Assistant", "Resend invite");

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith("ta-new"));
    expect(showToastMock).toHaveBeenCalledWith(
      "Invite resent to ta-new@smu.edu.sg.",
    );
  });

  it("offers no Resend invite once the assistant has signed in", async () => {
    renderPage();

    const row = await rowFor("Signed In Assistant");
    // No menu at all: with deactivation gone ([0.21.0]) a signed-in row's only
    // action is Remove from team.
    expect(
      within(row).queryByRole("button", {
        name: "More actions for Signed In Assistant",
      }),
    ).toBeNull();
  });
});

describe("TeachingAssistantsPage - email typo check", () => {
  function fill(email: string) {
    fireEvent.change(screen.getByLabelText(/SMU email/), {
      target: { value: email },
    });
  }

  it("pauses once on a near-miss domain and lets the instructor keep it", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(user({ id: "x" }));
    addMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();
    fill("ann@gmial.com");

    fireEvent.click(
      screen.getByRole("button", { name: "Add teaching assistant" }),
    );
    await screen.findByText(/Did you mean/);
    expect(mutateAsync).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Keep as typed" }));
    expect(screen.queryByText(/Did you mean/)).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Add teaching assistant" }),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Add to my team",
      }),
    );
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
  });

  it("swaps in the suggestion", async () => {
    renderPage();
    fill("ann@gmial.com");

    fireEvent.click(
      screen.getByRole("button", { name: "Add teaching assistant" }),
    );
    fireEvent.click(await screen.findByRole("button", { name: /^Use / }));

    expect(screen.getByLabelText(/SMU email/)).toHaveProperty(
      "value",
      "ann@gmail.com",
    );
  });

  it("pauses again if the address is edited and then restored", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(user({ id: "x" }));
    addMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();
    fill("ann@gmial.com");
    const submit = () =>
      fireEvent.click(
        screen.getByRole("button", { name: "Add teaching assistant" }),
      );

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

describe("TeachingAssistantsPage - adding and removing", () => {
  it("adds by email alone and says the same thing whatever happened", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(SIGNED_IN);
    addMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();

    fireEvent.change(screen.getByLabelText("SMU email"), {
      target: { value: "ta-old@smu.edu.sg" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Add teaching assistant" }),
    );
    // Nothing is sent until the instructor confirms the exact address.
    expect(mutateAsync).not.toHaveBeenCalled();
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Add to my team",
      }),
    );

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith("ta-old@smu.edu.sg"),
    );
    expect(screen.queryByLabelText(/Name/)).toBeNull();
    expect(showToastMock).toHaveBeenCalledWith(
      "ta-old@smu.edu.sg is on your team. New accounts get an email to set a password.",
    );
  });

  it("shows the server's refusal under the email field", async () => {
    const refusal =
      "This email can't be added. Contact the root administrator.";
    const { ApiError } = await import("../../api/client");
    const mutateAsync = vi.fn().mockRejectedValue(new ApiError(409, refusal));
    addMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();

    fireEvent.change(screen.getByLabelText("SMU email"), {
      target: { value: "someone@smu.edu.sg" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Add teaching assistant" }),
    );
    // Nothing is sent until the instructor confirms the exact address.
    expect(mutateAsync).not.toHaveBeenCalled();
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Add to my team",
      }),
    );

    // No jest-dom in this repo: assert on textContent.
    expect((await screen.findByRole("alert")).textContent).toContain(refusal);
  });

  it("returns to the field untouched when the instructor wants to edit", async () => {
    const mutateAsync = vi.fn();
    addMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();

    const field = screen.getByLabelText("SMU email");
    fireEvent.change(field, { target: { value: "wei.lin@smu.edu.sg" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Add teaching assistant" }),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Edit email",
      }),
    );

    expect(screen.queryByRole("dialog")).toBeNull();
    expect((field as HTMLInputElement).value).toBe("wei.lin@smu.edu.sg");
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("removes the assistant from my team only", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(SIGNED_IN);
    unlinkMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();

    const row = await rowFor("Signed In Assistant");
    fireEvent.click(
      within(row).getByRole("button", { name: "Remove from team" }),
    );
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Remove from team",
      }),
    );

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        taId: "ta-old",
        instructorId: "inst-1",
      }),
    );
  });
});
