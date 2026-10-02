import { defineConfig, devices } from "@playwright/test";

// Runs against the ephemeral stack in apps/e2e, which global-setup brings up.
// See docs/superpowers/specs/2026-10-01-playwright-smoke-suite-design.md.
export default defineConfig({
  testDir: "e2e",
  // One seeded user and one database are shared by every spec.
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  use: {
    baseURL: "http://localhost:5173",
    storageState: "e2e/.auth/instructor.json",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
