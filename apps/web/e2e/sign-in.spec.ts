import { expect, test } from "@playwright/test";

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a protected page redirects to sign in", async ({ page }) => {
    await page.goto("/check");
    await expect(page).toHaveURL("/login");
  });
});

test("the seeded instructor lands on the check page", async ({ page }) => {
  await page.goto("/check");
  await expect(
    page.getByRole("heading", { name: "Screen New Answers" }),
  ).toBeVisible();
  await expect(
    page.getByRole("complementary").getByText("E2E Instructor"),
  ).toBeVisible();
});
