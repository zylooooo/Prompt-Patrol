import ModelStatusBadge from "../ModelStatusBadge";
import { checkKeys } from "../../api/checks";
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

const FALLBACK = "checking detector";

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
  calibrationVersion = null,
}: {
  status?: string;
  statusFails?: boolean;
  capabilitiesFail?: boolean;
  calibrationVersion?: string | null;
} = {}) {
  vi.stubGlobal("fetch", (path: string) => {
    if (path === STATUS_PATH) {
      return statusFails
        ? Promise.reject(new Error("network down"))
        : ok({ status, model_version: CAPABILITIES.model_version });
    }
    return capabilitiesFail
      ? Promise.reject(new Error("network down"))
      : ok({ ...CAPABILITIES, calibration_version: calibrationVersion });
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

  it("says uncalibrated when the detector reports no calibration", async () => {
    stubApi();

    renderWithProviders(<ModelStatusBadge />);

    await waitFor(() =>
      expect(
        screen.getByText("roberta-base-openai-detector-v0 · uncalibrated"),
      ).toBeDefined(),
    );
  });

  it("names the calibration version once the detector reports one", async () => {
    stubApi({ calibrationVersion: "desklib-temp1.944-v1" });

    renderWithProviders(<ModelStatusBadge />);

    await waitFor(() =>
      expect(
        screen.getByText("roberta-base-openai-detector-v0 · desklib-temp1.944-v1"),
      ).toBeDefined(),
    );
  });

  it("keeps the old wording while the answer is still in flight", () => {
    vi.stubGlobal("fetch", () => new Promise(() => {}));

    renderWithProviders(<ModelStatusBadge />);

    expect(screen.getByText(FALLBACK)).toBeDefined();
  });

  it("says the detector is unavailable when it cannot be reached", async () => {
    // A dead detector is not a reason to blank the badge or claim a version,
    // and the red dot is spelled out rather than left to colour alone.
    stubApi({ capabilitiesFail: true, statusFails: true });

    renderWithProviders(<ModelStatusBadge />);

    await waitFor(() =>
      expect(screen.getByText("detector unavailable")).toBeDefined(),
    );
    expect(screen.queryByText(/roberta/)).toBeNull();
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
    // Spelled out visibly, not left to the amber dot alone.
    // (amber is also the pre-fetch default, so wait for the text itself).
    expect(await screen.findByText("detector starting up")).toBeDefined();
  });

  it("names the model once a detector that was loading becomes ready, without a reload", async () => {
    // The API only learns the model from the detector's /health once it is ready, so capabilities fetched while it
    // loads name no model. They are cached for an hour; the ready transition must refetch them.
    let detectorStatus = "loading";
    vi.stubGlobal("fetch", (path: string) => {
      if (path === STATUS_PATH) {
        return ok({ status: detectorStatus, model_version: null });
      }
      return ok({
        ...CAPABILITIES,
        model_version:
          detectorStatus === "ready" ? "desklib-meld-ensemble-v1" : null,
        calibration_version: null,
      });
    });

    const { client } = renderWithProviders(<ModelStatusBadge />);
    expect(await screen.findByText("detector starting up")).toBeDefined();

    detectorStatus = "ready";
    await client.refetchQueries({ queryKey: checkKeys.detectorStatus() });

    expect(
      await screen.findByText("desklib-meld-ensemble-v1 · uncalibrated"),
    ).toBeDefined();
  });

  it("says ready rather than naming a model before the API has heard one", async () => {
    vi.stubGlobal("fetch", (path: string) =>
      path === STATUS_PATH
        ? ok({ status: "ready", model_version: null })
        : ok({ ...CAPABILITIES, model_version: null, calibration_version: null }),
    );

    renderWithProviders(<ModelStatusBadge />);

    expect(await screen.findByText("detector ready")).toBeDefined();
    expect(screen.queryByText(/null|undefined/)).toBeNull();
  });

  it("goes red when the detector is down", async () => {
    stubApi({ status: "unavailable" });

    const { container } = renderWithProviders(<ModelStatusBadge />);

    await waitFor(() =>
      expect(dotClass(container)).toContain("bg-status-down"),
    );
    expect(screen.getByText("detector unavailable")).toBeDefined();
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
