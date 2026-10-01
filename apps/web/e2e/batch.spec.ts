import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// Hardcoded from serializeResultsCsv in src/lib/csv.ts: importing it pulls in
// src/types, whose extensionless imports fail tsconfig.node.json's nodenext.
const RESULTS_HEADER =
  "external_ref,question_text,answer_text,raw_score,verdict,verdict_text,model_version,calibration,note";

test("a batch upload downloads its results as CSV", async ({ page }) => {
  await page.goto("/check?tab=batch");
  await page.getByLabel("Upload CSV").setInputFiles("e2e/fixtures/answers.csv");
  await page.getByRole("button", { name: "Run 3 checks" }).click();

  // The worker polls SQS, so completion is not instant even with the stub.
  await expect(
    page.getByRole("status").filter({ hasText: "Batch complete." }),
  ).toHaveText(/3 flagged/, { timeout: 60_000 });

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download results (CSV)" }).click(),
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
