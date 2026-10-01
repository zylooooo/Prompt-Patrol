import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { expectNoA11yViolations, tabTo } from "./a11y.ts";

// Hardcoded from serializeResultsCsv in src/lib/csv.ts: importing it pulls in
// src/types, whose extensionless imports fail tsconfig.node.json's nodenext.
const RESULTS_HEADER =
  "external_ref,question_text,answer_text,raw_score,verdict,verdict_text,model_version,calibration,note";
const FIXTURE = "e2e/fixtures/answers.csv";

// The worker polls SQS, so completion is not instant even with the stub. The
// test timeout must outlast this wait, or a slow batch dies at the 30s default.
test.describe.configure({ timeout: 90_000 });
const expectBatchComplete = (page: Page) =>
  expect(
    page.getByRole("status").filter({ hasText: "Batch complete." }),
  ).toHaveText(/3 flagged/, { timeout: 60_000 });

const downloadButton = (page: Page) =>
  page.getByRole("button", { name: "Download results (CSV)" });

test("a batch upload downloads its results as CSV", async ({ page }) => {
  await page.goto("/check?tab=batch");
  await expectNoA11yViolations(page);
  await page.getByLabel("Upload CSV").setInputFiles(FIXTURE);
  await page.getByRole("button", { name: "Run 3 checks" }).click();

  await expectBatchComplete(page);
  await expectNoA11yViolations(page);

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    downloadButton(page).click(),
  ]);
  const [header, ...rows] = readFileSync(await download.path(), "utf8").split(
    "\r\n",
  );
  expect(header).toBe(RESULTS_HEADER);
  expect(rows.map((row) => row.split(",")[0]).sort()).toEqual([
    "e2e-001",
    "e2e-002",
    "e2e-003",
  ]);
});

test("a batch can be run and downloaded from the keyboard", async ({ page }) => {
  // The file input itself is hidden; "browse" is the keyboard route to the
  // picker. The OS picker is native UI, so the test answers it directly.
  // Listen before navigating: a keypress has no actionability wait, so it can
  // beat waitForEvent's interception setup if the two start together.
  const chooser = page.waitForEvent("filechooser");
  await page.goto("/check?tab=batch");
  await tabTo(page, page.getByRole("button", { name: "browse" }));
  await page.keyboard.press("Enter");
  await (await chooser).setFiles(FIXTURE);
  await tabTo(page, page.getByRole("button", { name: "Run 3 checks" }));
  await page.keyboard.press("Enter");

  await expectBatchComplete(page);
  await tabTo(page, downloadButton(page));
  await Promise.all([
    page.waitForEvent("download"),
    page.keyboard.press("Enter"),
  ]);
});
