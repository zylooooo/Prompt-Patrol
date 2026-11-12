import { useState } from "react";
import CheckPage from "../CheckPage";
import { renderWithProviders } from "../../test/render";
import { installDomStubs } from "../../test/dom-stubs";
import { ToastProvider } from "../../components/ToastProvider";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { checkAnswer } from "../../api/checks";
import { clearPreviousUserData } from "../../api/auth";
import { clearCheckDraft, readCheckDraft } from "../../lib/checkDraft";

/**
 * The bug this covers: switching between the Single answer and Batch (CSV)
 * tabs unmounted the other panel, so a half-typed answer came back empty.
 */

vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => ({
    user: { id: "u1", email: "i@smu.edu.sg", role: "instructor" },
  }),
}));

vi.mock("../../api/checks", async () => ({
  ...(await vi.importActual<typeof import("../../api/checks")>(
    "../../api/checks",
  )),
  hasScreeningAccess: () => true,
  checkAnswer: vi.fn(),
}));

// Strictness flag on, so the picker renders and its draft can be checked.
vi.mock("../../hooks/useChecks", async () => ({
  ...(await vi.importActual<typeof import("../../hooks/useChecks")>(
    "../../hooks/useChecks",
  )),
  useStrictnessLevels: () => ["lenient", "standard", "strict"],
}));

vi.mock("../../components/ResultPanel", () => ({
  default: () => null,
}));

vi.mock("../../components/ModelStatusBadge", () => ({
  default: () => null,
}));

// Stands in for the real batch panel: all that matters is whether its local
// state survives a trip to the other tab.
vi.mock("../../components/BatchTab", () => ({
  default: function BatchStub() {
    const [name, setName] = useState("");
    return (
      <input
        aria-label="Batch stub"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
    );
  },
}));

function renderPage(route = "/check") {
  return renderWithProviders(
    <ToastProvider>
      <CheckPage />
    </ToastProvider>,
    { route },
  );
}

const tab = (name: string) =>
  fireEvent.click(screen.getByRole("tab", { name }));

beforeEach(() => {
  installDomStubs();
  clearCheckDraft();
});
afterEach(() => cleanup());

describe("CheckPage tabs", () => {
  it("keeps the single-answer draft when switching to Batch and back", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Student answer"), {
      target: { value: "A half-typed student answer." },
    });
    fireEvent.change(screen.getByLabelText("Question context"), {
      target: { value: "Explain coupling." },
    });
    fireEvent.click(screen.getByRole("radio", { name: "Strict" }));

    tab("Batch (CSV)");
    expect(
      screen.queryByRole("tabpanel", { name: "Single answer" }),
    ).toBeNull();
    tab("Single answer");

    expect(
      screen.getByLabelText<HTMLTextAreaElement>("Student answer").value,
    ).toBe("A half-typed student answer.");
    expect(
      screen.getByLabelText<HTMLInputElement>("Question context").value,
    ).toBe("Explain coupling.");
    expect(
      screen
        .getByRole("radio", { name: "Strict" })
        .getAttribute("aria-checked"),
    ).toBe("true");
  });

  it("keeps the batch panel's state when switching to Single answer and back", () => {
    renderPage("/check?tab=batch");
    fireEvent.change(screen.getByLabelText("Batch stub"), {
      target: { value: "answers.csv" },
    });

    tab("Single answer");
    tab("Batch (CSV)");

    expect(screen.getByLabelText<HTMLInputElement>("Batch stub").value).toBe(
      "answers.csv",
    );
  });

  it("doesn't mount the batch panel until it is opened", () => {
    renderPage();
    expect(screen.queryByLabelText("Batch stub")).toBeNull();
  });

  it("keeps the draft when leaving the page via the sidebar and coming back", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Student answer"), {
      target: { value: "Typed before going to Check history." },
    });
    fireEvent.click(screen.getByRole("radio", { name: "Strict" }));
    cleanup(); // the route change unmounts the page

    renderPage();
    expect(
      screen.getByLabelText<HTMLTextAreaElement>("Student answer").value,
    ).toBe("Typed before going to Check history.");
    expect(
      screen
        .getByRole("radio", { name: "Strict" })
        .getAttribute("aria-checked"),
    ).toBe("true");
  });

  it("drops the draft after a successful check", async () => {
    vi.mocked(checkAnswer).mockResolvedValue(
      // Only the draft matters here, not how the result renders.
      {} as Awaited<ReturnType<typeof checkAnswer>>,
    );
    renderPage();
    fireEvent.change(screen.getByLabelText("Student answer"), {
      target: { value: "A long enough answer to check." },
    });
    expect(readCheckDraft("u1")).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Check answer" }));
    await waitFor(() => expect(readCheckDraft("u1")).toBeNull());
  });

  it("drops the draft on sign-out or a change of user", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Student answer"), {
      target: { value: "Someone else's student answer." },
    });
    clearPreviousUserData();
    expect(readCheckDraft("u1")).toBeNull();
  });
});
