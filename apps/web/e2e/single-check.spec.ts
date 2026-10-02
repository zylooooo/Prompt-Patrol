import { expect, test, type Page } from "@playwright/test";
import { expectNoA11yViolations, tabTo } from "./a11y.ts";

// The detector stub always scores 0.99, which every strictness threshold in
// checks_service.THRESHOLDS flags as ai_generated, shown as VERDICT_TEXT's
// "Likely AI-generated". The backend abstains under 10 words, so the answer
// must clear that as well as ANSWER_MIN_CHARS.
const ANSWER =
  "Dependency injection passes a component its collaborators from outside, so tests can swap in fakes.";

const verdict = (page: Page) =>
  page.getByRole("tabpanel").getByText("Likely AI-generated", { exact: true });

test("a single check shows the flagged verdict", async ({ page }) => {
  await page.goto("/check");
  await expectNoA11yViolations(page);
  await page.getByLabel("Student answer").fill(ANSWER);
  await page.getByRole("button", { name: "Check answer" }).click();

  await expect(verdict(page)).toBeVisible();
  await expectNoA11yViolations(page);
});

test("a single check can be run from the keyboard", async ({ page }) => {
  await page.goto("/check");
  await tabTo(page, page.getByLabel("Student answer"));
  await page.keyboard.type(ANSWER);
  await tabTo(page, page.getByRole("button", { name: "Check answer" }));
  await page.keyboard.press("Enter");

  await expect(verdict(page)).toBeVisible();
});
