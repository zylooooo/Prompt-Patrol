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
const createMock = vi.fn();
const setActiveMock = vi.fn();
vi.mock("../../hooks/useUsers", () => {
  const idle = () => ({ mutateAsync: vi.fn(), isPending: false });
  return {
    useMyAssistants: () => assistantsMock() as unknown,
    useCreateAccount: () => createMock() as unknown,
    useSetSupervisor: idle,
    useSetUserActive: () => setActiveMock() as unknown,
    useResendInvite: () => resendMock() as unknown,
  };
});

const user = (over: Partial<AppUser> & Pick<AppUser, "id">): AppUser => ({
  email: `${over.id}@smu.edu.sg`,
  name: null,
  role: "teaching_assistant",
  status: "active",
  provisionedBy: "inst-1",
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
  createMock.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  setActiveMock.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
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
    fireEvent.click(
      within(row).getByRole("button", {
        name: "More actions for Signed In Assistant",
      }),
    );
    await screen.findByRole("menuitem", { name: "Deactivate" });
    expect(
      screen.queryByRole("menuitem", { name: "Resend invite" }),
    ).toBeNull();
  });
});

describe("TeachingAssistantsPage - deactivate and reactivate", () => {
  it("offers Deactivate in the menu for a pending assistant", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(PENDING);
    setActiveMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();

    const row = await rowFor("New Assistant");
    await openMenuItem(row, "New Assistant", "Deactivate");
    fireEvent.click(
      await screen.findByRole("button", { name: "Deactivate account" }),
    );

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        id: "ta-new",
        active: false,
        reason: undefined,
      }),
    );
  });

  it("sends the typed reason with markup stripped", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(SIGNED_IN);
    setActiveMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();

    const row = await rowFor("Signed In Assistant");
    await openMenuItem(row, "Signed In Assistant", "Deactivate");
    fireEvent.change(await screen.findByLabelText(/Reason/), {
      target: { value: "  <img src=x onerror=alert(1)> on leave  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Deactivate account" }));

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        id: "ta-old",
        active: false,
        reason: "img src=x onerror=alert(1) on leave",
      }),
    );
  });

  it("sends no reason when the box is left blank", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(SIGNED_IN);
    setActiveMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();

    const row = await rowFor("Signed In Assistant");
    await openMenuItem(row, "Signed In Assistant", "Deactivate");
    fireEvent.click(
      await screen.findByRole("button", { name: "Deactivate account" }),
    );

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        id: "ta-old",
        active: false,
        reason: undefined,
      }),
    );
  });

  it("reactivates a deactivated assistant from the menu without a dialog", async () => {
    const off = user({
      id: "ta-off",
      name: "Paused Assistant",
      status: "deactivated",
    });
    assistantsMock.mockReturnValue({
      data: [off],
      isPending: false,
      isError: false,
    });
    const mutateAsync = vi.fn().mockResolvedValue(off);
    setActiveMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();

    const row = await rowFor("Paused Assistant");
    await openMenuItem(row, "Paused Assistant", "Reactivate");

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({
        id: "ta-off",
        active: true,
        reason: undefined,
      }),
    );
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
    createMock.mockReturnValue({ mutateAsync, isPending: false });
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
    createMock.mockReturnValue({ mutateAsync, isPending: false });
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
