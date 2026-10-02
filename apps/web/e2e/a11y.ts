import { AxeBuilder } from "@axe-core/playwright";
import { expect, type Locator, type Page } from "@playwright/test";

export async function expectNoA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  const summary = violations.map((v) => ({
    id: v.id,
    help: v.help,
    nodes: v.nodes.map((n) => `${n.target.join(" ")}: ${n.failureSummary}`),
  }));
  expect(summary, JSON.stringify(summary, null, 2)).toEqual([]);
}

// Presses Tab until `target` holds focus. Capped so a focus trap, or a control
// keyboard users cannot reach, fails the test instead of hanging it.
export async function tabTo(page: Page, target: Locator) {
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press("Tab");
    if (await target.and(page.locator(":focus")).count()) return;
  }
  throw new Error(`Tab never reached ${target.toString()}`);
}
