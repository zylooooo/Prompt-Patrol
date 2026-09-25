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
vi.mock("../../hooks/useUsers", () => {
  const idle = () => ({ mutateAsync: vi.fn(), isPending: false });
  return {
    useMyAssistants: () => assistantsMock() as unknown,
    useCreateAccount: () => createMock() as unknown,
    useSetSupervisor: idle,
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
});
afterEach(cleanup);

describe("TeachingAssistantsPage - pending invites", () => {
  it("resends the invite for a pending assistant and says so", async () => {
    const mutateAsync = vi.fn().mockResolvedValue(PENDING);
    resendMock.mockReturnValue({ mutateAsync, isPending: false });
    renderPage();

    const row = await rowFor("New Assistant");
    fireEvent.click(within(row).getByRole("button", { name: "Resend invite" }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith("ta-new"));
    expect(showToastMock).toHaveBeenCalledWith(
      "Invite resent to ta-new@smu.edu.sg.",
    );
  });

  it("offers no Resend invite once the assistant has signed in", async () => {
    renderPage();

    const row = await rowFor("Signed In Assistant");
    expect(
      within(row).queryByRole("button", { name: "Resend invite" }),
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
