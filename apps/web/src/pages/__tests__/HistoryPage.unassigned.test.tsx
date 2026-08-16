import HistoryPage from "../HistoryPage";
import { MemoryRouter } from "react-router-dom";
import { installDomStubs } from "../../test/dom-stubs";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

/**
 * The dead end this covers: a newly provisioned TA has no instructor, so the
 * history query 403s. The page used to swallow that and render "No checks yet -
 * run your first check from the Check answers page", pointing them at the one
 * page that also tells them they cannot do anything.
 */

const useAuthMock = vi.fn();
vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => useAuthMock() as unknown,
}));

const hasScreeningAccessMock = vi.fn();
const listHistoryMock = vi.fn();
vi.mock("../../api/checks", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/checks")>(
      "../../api/checks",
    );
  return {
    ...actual,
    hasScreeningAccess: (...args: unknown[]) =>
      hasScreeningAccessMock(...args) as boolean,
    listHistory: (...args: unknown[]) => listHistoryMock(...args) as unknown,
  };
});

const ta = { email: "ta@smu.edu.sg", role: "teaching_assistant" };

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  installDomStubs({ matches: true });
  vi.clearAllMocks();
  useAuthMock.mockReturnValue({
    user: ta,
    isPending: false,
    isError: false,
    error: null,
  });
});
afterEach(cleanup);

describe("HistoryPage — teaching assistant with no instructor", () => {
  it("explains the blocker instead of claiming there is no history yet", async () => {
    hasScreeningAccessMock.mockReturnValue(false);
    listHistoryMock.mockRejectedValue(new Error("403"));

    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText("You are not assigned to an instructor yet"),
      ).toBeDefined(),
    );
    expect(screen.queryByText("No checks yet")).toBeNull();
  });

  it("does not send them to a page that will also turn them away", async () => {
    hasScreeningAccessMock.mockReturnValue(false);
    listHistoryMock.mockRejectedValue(new Error("403"));

    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText("You are not assigned to an instructor yet"),
      ).toBeDefined(),
    );
    expect(screen.queryByText(/Run your first check/)).toBeNull();
  });

  it("still shows the ordinary empty state to an assigned user", async () => {
    hasScreeningAccessMock.mockReturnValue(true);
    listHistoryMock.mockResolvedValue([]);

    renderPage();

    await waitFor(() =>
      expect(screen.getByText("No checks yet")).toBeDefined(),
    );
    expect(
      screen.queryByText("You are not assigned to an instructor yet"),
    ).toBeNull();
  });

  it("reports a genuine failure as a failure, with a retry", async () => {
    hasScreeningAccessMock.mockReturnValue(true);
    listHistoryMock.mockRejectedValue(new Error("server exploded"));

    renderPage();

    await waitFor(() =>
      expect(screen.getByText("Could not load your history")).toBeDefined(),
    );
    expect(screen.getByRole("button", { name: "Try again" })).toBeDefined();
    expect(screen.queryByText("No checks yet")).toBeNull();
  });
});
