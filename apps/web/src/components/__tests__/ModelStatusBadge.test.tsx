import ModelStatusBadge from "../ModelStatusBadge";
import { renderWithProviders } from "../../test/render";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";

/**
 * The badge is the first thing wired to the detector, so it is also the first
 * thing that can be broken by the detector being down. It must degrade to what
 * it said before this was wired at all, never to a blank or a guess.
 *
 * The dot carries a second, separate claim: whether the service can score right
 * now. Green while the model is still loading would send someone to run a check
 * that is going to fail, so each state is pinned here.
 */

const CAPABILITIES = {
  model_version: "roberta-base-openai-detector-v0",
  requires_question_text: false,
  min_answer_chars: 10,
  max_answer_chars: 10000,
  strictness_levels: [{ level: "standard", target_fpr: 0.01 }],
  supports_explanation: false,
  supports_spans: false,
};

const FALLBACK = "demo detector · scores uncalibrated";

const STATUS_PATH = "/api/detector/status";

function ok(body: unknown) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  });
}

/** Routes by path so the two queries can be answered independently. */
function stubApi({
  status = "ready",
  statusFails = false,
  capabilitiesFail = false,
}: {
  status?: string;
  statusFails?: boolean;
  capabilitiesFail?: boolean;
} = {}) {
  vi.stubGlobal("fetch", (path: string) => {
    if (path === STATUS_PATH) {
      return statusFails
        ? Promise.reject(new Error("network down"))
        : ok({ status, model_version: CAPABILITIES.model_version });
    }
    return capabilitiesFail
      ? Promise.reject(new Error("network down"))
      : ok(CAPABILITIES);
  });
}

function dotClass(container: HTMLElement): string {
  return container.querySelector("[aria-hidden]")?.className ?? "";
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ModelStatusBadge", () => {
  it("names the model once the detector answers", async () => {
    stubApi();

    renderWithProviders(<ModelStatusBadge />);

    await waitFor(() =>
      expect(screen.getByText(/roberta-base-openai-detector-v0/)).toBeDefined(),
    );
  });

  it("keeps the old wording while the answer is still in flight", () => {
    vi.stubGlobal("fetch", () => new Promise(() => {}));

    renderWithProviders(<ModelStatusBadge />);

    expect(screen.getByText(FALLBACK)).toBeDefined();
  });

  it("keeps the old wording when the detector cannot be reached", async () => {
    // A dead detector is not a reason to blank the badge or claim a version.
    stubApi({ capabilitiesFail: true, statusFails: true });

    renderWithProviders(<ModelStatusBadge />);

    await waitFor(() => expect(screen.getByText(FALLBACK)).toBeDefined());
  });

  it("goes green once the detector can score", async () => {
    stubApi({ status: "ready" });

    const { container } = renderWithProviders(<ModelStatusBadge />);

    await waitFor(() =>
      expect(dotClass(container)).toContain("bg-status-ready"),
    );
    expect(screen.getByText(/Detector ready/)).toBeDefined();
  });

  it("stays amber while the model is still loading", async () => {
    // The window this whole change exists to make visible.
    stubApi({ status: "loading" });

    const { container } = renderWithProviders(<ModelStatusBadge />);

    await waitFor(() =>
      expect(dotClass(container)).toContain("bg-status-warming"),
    );
    expect(screen.getByText(/starting up/)).toBeDefined();
  });

  it("goes red when the detector is down", async () => {
    stubApi({ status: "unavailable" });

    const { container } = renderWithProviders(<ModelStatusBadge />);

    await waitFor(() =>
      expect(dotClass(container)).toContain("bg-status-down"),
    );
    expect(screen.getByText(/unavailable/)).toBeDefined();
  });

  it("goes red rather than amber when the status call itself fails", async () => {
    // An unreachable API tells us nothing about the detector, and amber would
    // read as "nearly there" when nobody has any idea.
    stubApi({ statusFails: true });

    const { container } = renderWithProviders(<ModelStatusBadge />);

    await waitFor(() =>
      expect(dotClass(container)).toContain("bg-status-down"),
    );
  });

  it("starts amber rather than red before the first answer arrives", () => {
    vi.stubGlobal("fetch", () => new Promise(() => {}));

    const { container } = renderWithProviders(<ModelStatusBadge />);

    expect(dotClass(container)).toContain("bg-status-warming");
  });
});
