import { expect, test } from "@playwright/test";

// The detector stub always scores 0.99, which every strictness threshold in
// checks_service.THRESHOLDS flags as ai_generated, shown as VERDICT_TEXT's
// "Likely AI-generated". The backend abstains under 10 words, so the answer
// must clear that as well as ANSWER_MIN_CHARS.
const ANSWER =
  "Dependency injection passes a component its collaborators from outside, so tests can swap in fakes.";

test("a single check shows the flagged verdict", async ({ page }) => {
  await page.goto("/check");
  await page.getByLabel("Student answer").fill(ANSWER);
  await page.getByRole("button", { name: "Check answer" }).click();

  await expect(
    page.getByRole("tabpanel").getByText("Likely AI-generated", { exact: true }),
  ).toBeVisible();
});
