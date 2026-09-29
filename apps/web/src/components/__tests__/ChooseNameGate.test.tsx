import ChooseNameGate from "../ChooseNameGate";
import { installDomStubs } from "../../test/dom-stubs";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const authMock = vi.fn();
vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => authMock() as unknown,
}));

const renameMock = vi.fn();
vi.mock("../../hooks/useUsers", () => ({
  useUpdateDisplayName: () => renameMock() as unknown,
}));

const person = (name: string | null) => ({
  user: {
    id: "u-1",
    email: "wei@smu.edu.sg",
    name,
    role: "teaching_assistant",
    supervisorIds: [],
  },
});

function renderGate() {
  return render(
    <MemoryRouter>
      <ChooseNameGate>
        <p>the app</p>
      </ChooseNameGate>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  installDomStubs({ matches: false });
  vi.clearAllMocks();
  renameMock.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
});
afterEach(cleanup);

describe("ChooseNameGate", () => {
  it("lets a named person straight through", () => {
    authMock.mockReturnValue(person("Wei Lin"));
    renderGate();

    expect(screen.getByText("the app")).toBeTruthy();
  });

  it("asks an unnamed person for a name before anything else", () => {
    authMock.mockReturnValue(person(null));
    renderGate();

    expect(screen.queryByText("the app")).toBeNull();
    expect(
      screen.getByRole("heading", { name: "What should we call you?" }),
    ).toBeTruthy();
    expect(screen.getByText(/wei@smu\.edu\.sg/).className).toContain(
      "font-mono",
    );
  });

  it("saves the trimmed name for the signed-in person", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({});
    renameMock.mockReturnValue({ mutateAsync, isPending: false });
    authMock.mockReturnValue(person(null));
    renderGate();

    fireEvent.change(screen.getByLabelText("Your name"), {
      target: { value: "  Wei Lin " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ id: "u-1", name: "Wei Lin" }),
    );
  });

  it("won't submit a blank name", () => {
    authMock.mockReturnValue(person(null));
    renderGate();

    fireEvent.change(screen.getByLabelText("Your name"), {
      target: { value: "   " },
    });

    expect(screen.getByRole("button", { name: "Continue" })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("says so when saving fails", async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error("down"));
    renameMock.mockReturnValue({ mutateAsync, isPending: false });
    authMock.mockReturnValue(person(null));
    renderGate();

    fireEvent.change(screen.getByLabelText("Your name"), {
      target: { value: "Wei" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Couldn't save your name",
    );
  });
});
